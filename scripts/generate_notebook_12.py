"""Committed generator for notebook 12 -- criticality representation via
per-sample edge gates (self-supervised, reconstruction-only pivot).

Notebook 11's generator lives OUTSIDE this repository and is therefore not
reproducible -- this module exists to fix exactly that: it is the single
source of truth for `notebooks/project_flow/12_*.ipynb`. The notebook itself
is GENERATED OUTPUT, never hand-edited.

Pipeline (`main`): build the in-memory notebook -> assign deterministic cell
ids -> `nbformat.validate` -> `ast.parse` every code cell -> write to disk.
Running papermill against the written file (smoke or full) is a separate,
manual step -- this module never launches papermill itself.

GOTCHA (hard-won from notebook 11's now-lost generator): a Python docstring
(`\"\"\"...\"\"\"`) embedded inside a cell-source string wrapped in
`'''...'''` would NOT break this generator (different quote family), but for
safety no cell body defined below uses a triple-quoted docstring internally
-- every helper function documents itself with `#` comments instead, exactly
as this file's own docstrings above never appear inside a cell string.

References:
  - spec: sdd/notebook-12-criticality-representation/spec
  - design: sdd/notebook-12-criticality-representation/design
  - PR1: src/chec_impacto/models/mgcecdl_graph.py
  - PR2: src/chec_impacto/interpretability/mgcecdl_graph.py,
         src/chec_impacto/models/mgcecdl_graph_search.py
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_11_PATH = REPO_ROOT / "notebooks" / "project_flow" / "11_mgcecdl_regression_budget.ipynb"
NOTEBOOK_12_PATH = REPO_ROOT / "notebooks" / "project_flow" / "12_criticality_edge_gates.ipynb"

# Literal feature/edge counts this generator (and the notebook it emits) must
# never hardcode -- every dimension is derived at runtime from the adjacency
# matrix, the feature list, or an edge index (spec: "Runtime-derived gate
# dimensions").
FORBIDDEN_LITERALS = ("70", "74", "75", "56", "71", "73")

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
# Cell source constants
#
# Every cell body below uses `'''...'''` at the Python level (this file), and
# never a docstring inside the emitted cell -- see the module docstring's
# GOTCHA note.
# ---------------------------------------------------------------------------

_MD_TITLE = '''\
# 12. Representacion de criticidad via gates de arista por muestra (M-GCECDL)

Pivote auto-supervisado: `MGCECDLRegressor` se usa exclusivamente como
autoencoder -- `x -> encode -> z -> gates -> propagate -> encode -> decode ->
x_hat` -- entrenado UNICAMENTE contra su propia reconstruccion de `x`, el
kernel del grafo experto fijo, y un prior de desviacion de gate. Ningun
objetivo supervisado entra jamas a la perdida.

Los clusters son regimenes de grafo por vano sobre el vector de gates de
dimension `E`; se validan contra una cantidad que el modelo NUNCA vio durante
el entrenamiento -- el `UITI_VANO` futuro acumulado por vano, en una
particion cronologicamente FUTURA.

Generado por `scripts/generate_notebook_12.py` (COMMITTED, reproducible --
a diferencia del generador de la libreta 11, que vivia fuera de este
repositorio). Ver `sdd/notebook-12-criticality-representation/{spec,design}`
para el contrato completo.
'''

_MD_DIAGRAM = '''\
## Diagrama del flujo de datos

```mermaid
flowchart TD
    A["procesar_dataset_completo (seleccion nb12-local)"] --> B["reinyectar_target_como_feature (UITI_VANO)"]
    B --> C["construir_edge_index (adyacencia experta fija)"]
    C --> D["split_cronologico_p70 (pasado / futuro)"]
    D --> E["entrenar_gated_autoencoder (SOLO pasado)"]
    E --> F["agrupar_gates_por_vano"]
    F --> G["KMeans (K derivado de los datos)"]
    G --> H["asociacion_criticidad vs UITI_VANO futuro acumulado"]
```
'''

_CODE_PARAMETERS = '''\
# Celda de parametros (papermill). Sobrescribir con `-p mode full` para la corrida real.
# El default es "smoke" a proposito -- ver la libreta 11 para el mismo patron.
mode = "smoke"
'''

_MD_BOOTSTRAP = '''\
## Bootstrap: raiz del repo, `sys.path` y guarda de precondiciones

Sigue el mismo patron obligatorio que la libreta 11: falla rapido y con un
mensaje accionable si los modulos de la representacion gated no son
importables.
'''

_CODE_BOOTSTRAP = '''\
import sys
from pathlib import Path


# Sube desde el cwd hasta el checkout, para correr desde cualquier directorio.
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
FIGURES_DIR = PROJECT_ROOT / "reports" / "interpretability" / "figures"

for path_to_add in (PROJECT_ROOT, SRC_DIR):
    if str(path_to_add) not in sys.path:
        sys.path.insert(0, str(path_to_add))
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

print("PROJECT_ROOT:", PROJECT_ROOT)
print("DATA_DIR:    ", DATA_DIR)
print("FIGURES_DIR: ", FIGURES_DIR)

# --- Guarda de precondiciones: sonda de import, nunca una implementacion sustituta ---
try:
    from chec_impacto.models import (
        GatedSelfSupervisedLoss,
        GraphGatedMGCECDLRegressor,
        construir_edge_index,
        entrenar_gated_autoencoder,
        reinyectar_target_como_feature,
    )
    from chec_impacto.interpretability import (
        agrupar_gates_por_vano,
        asociacion_criticidad,
        assert_fecha_excluded_from_features,
        control_permutacion_grados,
        diagnostico_persistencia,
        ejecutar_control_permutacion_grados,
        estadistico_colapso,
        guardia_proxy_univariante,
        linea_base_sin_grafo,
        seleccionar_k_datos,
        split_cronologico_p70,
        tabla_desviacion_aristas,
        tabla_grado_features,
        uiti_futuro_por_vano,
    )
    from chec_impacto.models import (
        LAMBDA_DEV_CHOICES,
        LAMBDA_MI_CHOICES,
        construir_objetivo_gated,
        mean_pairwise_ari,
        resumen_barrido_lambda_dev,
        resumen_barrido_lambda_mi,
    )
except ImportError as exc:
    raise SystemExit(
        "Los modulos de la representacion gated (models/mgcecdl_graph.py, "
        "interpretability/mgcecdl_graph.py, models/mgcecdl_graph_search.py) no son "
        f"importables desde {SRC_DIR}. Verifica que corres desde el checkout y que el "
        "entorno tiene torch/optuna/umap instalados (pip install -r requirements.txt)."
    ) from exc

from scripts.build_nb12_variable_selection import build_nb12_variable_selection

print("Guarda OK: modulos de la representacion gated (PR1 + PR2) importables.")
'''

_CODE_IMPORTS = '''\
import time

import numpy as np
import pandas as pd
import torch
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from chec_impacto.data import construir_matriz_adyacencia_mgcecdl, procesar_dataset_completo
from chec_impacto.models import MGCECDLRegressor
from chec_impacto.training import (
    calcular_estadisticas_reconstruccion_mgcecdl,
    construir_modalidades_mgcecdl,
    resolve_training_device,
    run_optuna_study,
)

RANDOM_STATE = 42
DEVICE = resolve_training_device("auto")
print("Dispositivo de entrenamiento resuelto:", DEVICE)
if DEVICE.type == "cpu":
    print("AVISO: se entrenara en CPU. Con mode='full' esto puede tardar horas.")
'''

_MD_CONFIG = '''\
## Configuracion del presupuesto (`smoke` vs `full`) y quiebre de semillas

Sigue el diseno D3: las semillas de BUSQUEDA (`SEEDS_SEARCH`) estan
CUARENTENADAS de las semillas de la compuerta de aceptacion (`SEEDS_GATE`) --
optimizar y evaluar con el mismo conjunto de semillas destruiria el valor
evidencial de la compuerta. `K_SEARCH` es una constante de tiempo de
busqueda unicamente; el K reportado se deriva de los datos mas adelante.
'''

_CODE_CONFIG = '''\
if mode not in ("smoke", "full"):
    raise ValueError(f"mode desconocido: {mode!r} -- se esperaba 'smoke' o 'full'.")

# Semillas de busqueda: nunca se re-usan para evaluar la compuerta de aceptacion.
SEEDS_SEARCH = (0, 1, 2)
# K_SEARCH es una constante de tiempo de BUSQUEDA unicamente -- el objetivo de Optuna
# nunca devuelve un "K": el K reportado se deriva de los datos mas abajo
# (seleccionar_k_datos), nunca sustituido silenciosamente por este valor.
K_SEARCH = 4

if mode == "smoke":
    # Prueba de cableado: submuestra pequena y presupuesto minimo.
    SEEDS_GATE = (10, 11)
    SMOKE_EVENT_SUBSAMPLE = 2000
    TAU_REFERENCE_EPOCHS = 2
    SEARCH_EPOCHS = 2
    OPTUNA_N_TRIALS = 2
    LAMBDA_SWEEP_EPOCHS = 2
    GATE_EPOCHS = 2
    ABLATION_EPOCHS = 2
    COST_CEILING_SECONDS = 900.0
else:
    # Semillas de la compuerta de aceptacion: 5, disjuntas de SEEDS_SEARCH (diseno D3).
    SEEDS_GATE = (10, 11, 12, 13, 14)
    SMOKE_EVENT_SUBSAMPLE = None
    TAU_REFERENCE_EPOCHS = 20
    SEARCH_EPOCHS = 20
    OPTUNA_N_TRIALS = 10
    LAMBDA_SWEEP_EPOCHS = 20
    GATE_EPOCHS = 30
    ABLATION_EPOCHS = 20
    # Techo declarado por el usuario para la fase costosa (busqueda Optuna): si la
    # proyeccion de la celda de pronostico de costo lo supera, NO se lanza la busqueda
    # completa y se usan hiperparametros de respaldo en su lugar.
    COST_CEILING_SECONDS = 4.0 * 3600.0

ARI_STABILITY_THRESHOLD = 0.3

print(f"mode={mode!r} | SEEDS_SEARCH={SEEDS_SEARCH} | SEEDS_GATE={SEEDS_GATE} | K_SEARCH={K_SEARCH}")
print(f"COST_CEILING_SECONDS={COST_CEILING_SECONDS}")
'''

_MD_DATA_LOAD = '''\
## 1. Carga de datos: seleccion nb12-local + reinyeccion de `UITI_VANO`

La seleccion nb12-local recupera `DURACION, TOT_USUS, UITI, COD_CAUSA` sobre
la seleccion compartida (`data/Variables_seleccion.xlsx`, jamas modificada
-- ver `scripts/build_nb12_variable_selection.py`). `UITI_VANO` se reinyecta
como feature endogena porque `preprocessing.py` la excluye de `features`
deliberadamente (ver D5 del diseno).
'''

_CODE_DATA_LOAD = '''\
VENTANA_CLIMATICA_HORAS = 12
FILTRO_UITI_MAX = None

DATASET_PATH = DATA_DIR / "Indicadores_vano_v3.csv"
derived_selection_path = build_nb12_variable_selection()
print("Seleccion derivada nb12-local:", derived_selection_path)

datos_procesados = procesar_dataset_completo(
    path_clima=DATASET_PATH,
    path_variables_seleccion=derived_selection_path,
    use_sampling=False,
    min_samples_per_codigo=5,
    target="UITI_VANO",
    filtro_uiti_max=FILTRO_UITI_MAX,
    ventana_climatica_horas=VENTANA_CLIMATICA_HORAS,
)

assert "UITI_VANO" not in datos_procesados["features"], (
    "UITI_VANO no debe estar en features antes de la reinyeccion explicita "
    "(preprocessing.py excluye el target de X por diseno)."
)

X_without_target = datos_procesados["X"]
features_without_target = list(datos_procesados["features"])

X_with_target, features_with_target = reinyectar_target_como_feature(
    datos_procesados, nombre_target="UITI_VANO"
)
assert len(features_with_target) == len(features_without_target) + 1
assert features_with_target[-1] == "UITI_VANO"

df_identidad = datos_procesados["df_original_copy"].reset_index(drop=True)
assert len(df_identidad) == X_with_target.shape[0] == X_without_target.shape[0]

if SMOKE_EVENT_SUBSAMPLE is not None and len(df_identidad) > SMOKE_EVENT_SUBSAMPLE:
    rng = np.random.RandomState(RANDOM_STATE)
    subsample_idx = np.sort(
        rng.choice(len(df_identidad), size=SMOKE_EVENT_SUBSAMPLE, replace=False)
    )
    X_with_target = X_with_target[subsample_idx]
    X_without_target = X_without_target[subsample_idx]
    df_identidad = df_identidad.iloc[subsample_idx].reset_index(drop=True)

print("X (con UITI_VANO):", X_with_target.shape, "| features:", len(features_with_target))
print("X (sin UITI_VANO, brazo de ablacion):", X_without_target.shape,
      "| features:", len(features_without_target))
'''

_MD_GRAPH = '''\
## 2. Adyacencia experta, indice de aristas y reporte de grado por feature

Se construyen DOS grafos: el brazo principal (con `UITI_VANO` reinyectada) y
el brazo de ablacion (sin ella) -- spec "UITI_VANO ablation and proxy
guard". Las features de grado 0 (`FECHA_OPERACION_TRF`, `LONG_CRUCETA`) se
reportan como no alcanzables por ningun gate por muestra.
'''

_CODE_GRAPH = '''\
A_with, preserved_edges_with = construir_matriz_adyacencia_mgcecdl(
    features_with_target, ventana_climatica_horas=VENTANA_CLIMATICA_HORAS,
)
edge_index_with = construir_edge_index(A_with, features_with_target, preserved_edges_with)

A_without, preserved_edges_without = construir_matriz_adyacencia_mgcecdl(
    features_without_target, ventana_climatica_horas=VENTANA_CLIMATICA_HORAS,
)
edge_index_without = construir_edge_index(A_without, features_without_target, preserved_edges_without)

print(f"Brazo con UITI_VANO:  p={len(features_with_target)}  E={edge_index_with.n_edges}")
print(f"Brazo sin UITI_VANO:  p={len(features_without_target)}  E={edge_index_without.n_edges}")

degree_table = tabla_grado_features(features_with_target, edge_index_with)
ungatable = degree_table.loc[degree_table["ungatable"], "feature"].tolist()
print("Features no alcanzables por ningun gate (grado 0):", ungatable)
for expected_feature in ("FECHA_OPERACION_TRF", "LONG_CRUCETA"):
    if expected_feature in ungatable:
        print(f"  -> {expected_feature}: confirmada de grado 0 en esta corrida.")
    elif expected_feature in features_with_target:
        row = degree_table.loc[degree_table["feature"] == expected_feature].iloc[0]
        print(f"  -> {expected_feature}: presente con grado {int(row['degree'])} (no de grado 0 aqui).")
'''

_MD_SPLIT = '''\
## 3. Particion cronologica (percentil 70 de `FECHA`)

El corte se DERIVA en tiempo de ejecucion (`split_cronologico_p70`), nunca
un literal fijo. El entrenamiento solo ve la ventana PASADA; la ventana
FUTURA se reserva integramente para validacion (`UITI_VANO` acumulado por
vano y conteo de eventos).
'''

_CODE_SPLIT = '''\
assert_fecha_excluded_from_features(features_with_target)

past_mask, future_mask, fecha_corte = split_cronologico_p70(df_identidad["FECHA"])
print(f"Corte cronologico p70 de FECHA: {fecha_corte}")
print(f"Filas en pasado: {int(past_mask.sum())} | Filas en futuro: {int(future_mask.sum())}")

X_past_with_target = X_with_target[past_mask]
X_past_without_target = X_without_target[past_mask]
circuito_past = df_identidad.loc[past_mask, "CIRCUITO"].to_numpy()
fid_vano_past = df_identidad.loc[past_mask, "FID_VANO"].to_numpy()

feature_mean_with, feature_std_with = calcular_estadisticas_reconstruccion_mgcecdl(X_past_with_target)
feature_mean_without, feature_std_without = calcular_estadisticas_reconstruccion_mgcecdl(
    X_past_without_target
)
'''

_MD_HELPERS = '''\
## 4. Funciones auxiliares de entrenamiento (constructor de modelo/perdida)

`hidden_dim=64`, `embed_dim=96`, `batch_size=1024` quedan FIJOS (diseno D3,
poda validada en la libreta 11); `reconstruction_normalization="soft"` se
pasa explicitamente y se afirma -- nunca `"clip"` (ver D2 y la clase
`GatedSelfSupervisedLoss`, que ya rechaza `"clip"` en su `__init__`).
'''

_CODE_HELPERS = '''\
FIXED_HIDDEN_DIM = 64
FIXED_EMBED_DIM = 96
FIXED_BATCH_SIZE = 1024
RECONSTRUCTION_NORMALIZATION = "soft"
assert RECONSTRUCTION_NORMALIZATION == "soft", "notebook 12 nunca usa la normalizacion 'clip'."


def format_duration(seconds):
    seconds = int(max(seconds, 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def build_model(features, adjacency, edge_index, *, alpha, dropout):
    # Se reconstruyen los indices de modalidad en cada llamada: son baratos y esto evita
    # que una corrida herede estado de la anterior.
    modality_indices = construir_modalidades_mgcecdl(list(features))
    base = MGCECDLRegressor(
        modality_feature_indices=modality_indices,
        hidden_dim=FIXED_HIDDEN_DIM, embed_dim=FIXED_EMBED_DIM, dropout=dropout,
    )
    return GraphGatedMGCECDLRegressor(
        base=base, adjacency=adjacency, edge_index=edge_index, alpha=alpha,
    ).to(DEVICE)


def build_loss(feature_mean, feature_std, adjacency, *, lambda_reconstruction,
               lambda_mutual_information, lambda_gate_deviation):
    return GatedSelfSupervisedLoss(
        feature_mean=feature_mean, feature_std=feature_std, adjacency_matrix=adjacency,
        lambda_reconstruction=lambda_reconstruction,
        lambda_mutual_information=lambda_mutual_information,
        lambda_gate_deviation=lambda_gate_deviation,
        reconstruction_normalization=RECONSTRUCTION_NORMALIZATION,
    )


def entrenar_y_agrupar(*, features, adjacency, edge_index, feature_mean, feature_std,
                        X_past_arr, circuito_arr, fid_vano_arr, alpha, dropout,
                        lambda_reconstruction, lambda_mutual_information, lambda_gate_deviation,
                        epochs, seed, lr=1e-3, weight_decay=1e-5, optimizer_name="adamw"):
    # Entrena un modelo gated FRESCO (nunca reutiliza pesos de una corrida anterior) y
    # devuelve, ademas del resultado de entrenamiento, los gates promediados por vano.
    model = build_model(features, adjacency, edge_index, alpha=alpha, dropout=dropout)
    loss_fn = build_loss(
        feature_mean, feature_std, adjacency,
        lambda_reconstruction=lambda_reconstruction,
        lambda_mutual_information=lambda_mutual_information,
        lambda_gate_deviation=lambda_gate_deviation,
    )
    result = entrenar_gated_autoencoder(
        model, loss_fn, X_past_arr, epochs=epochs, seed=seed, lr=lr,
        weight_decay=weight_decay, optimizer_name=optimizer_name, device=DEVICE,
    )
    trained_model = result["model"]
    trained_model.eval()
    with torch.no_grad():
        X_tensor = torch.as_tensor(np.asarray(X_past_arr), dtype=torch.float32).to(DEVICE)
        model_output = trained_model(X_tensor)
        # The full-batch pass is needed for the per-sample gates; the achieved
        # `mutual_information_normalized` comes straight from `result`, which
        # `entrenar_gated_autoencoder` tracks per epoch.
        gates = model_output["edge_gates"].cpu().numpy()
    gate_means, vano_index = agrupar_gates_por_vano(gates, circuito_arr, fid_vano_arr)
    return result, gate_means, vano_index
'''

_MD_TAU = '''\
## 5. Derivacion de `tau` (cota de factibilidad de reconstruccion)

`tau = media(recon_ref) + 2*desv(recon_ref)` sobre una corrida de REFERENCIA
con `alpha=0.0` (que reproduce exactamente el forward sin grafo, prueba RED
`test_alpha_zero_recovers_base_forward_exactly`), `lambda_dev=0.0`. Nunca un
literal (diseno D4).
'''

_CODE_TAU = '''\
reference_reconstructions = []
for seed in SEEDS_SEARCH:
    reference_result, _, _ = entrenar_y_agrupar(
        features=features_with_target, adjacency=A_with, edge_index=edge_index_with,
        feature_mean=feature_mean_with, feature_std=feature_std_with,
        X_past_arr=X_past_with_target, circuito_arr=circuito_past, fid_vano_arr=fid_vano_past,
        alpha=0.0, dropout=0.1, lambda_reconstruction=0.01, lambda_mutual_information=0.01,
        lambda_gate_deviation=0.0, epochs=TAU_REFERENCE_EPOCHS, seed=seed,
    )
    reference_reconstructions.append(reference_result["reconstruction_loss_raw"])

tau = float(np.mean(reference_reconstructions) + 2.0 * np.std(reference_reconstructions))
print(f"tau (cota de factibilidad de reconstruccion) = {tau:.6f}")
'''

_MD_COST_FORECAST = '''\
## 6. Pronostico de costo (compuerta obligatoria antes de la fase costosa)

Ninguna corrida gated de dos pasadas se ha cronometrado antes en esta
maquina -- esta celda MIDE, no asume. Se cronometra UNA corrida completa y se
proyecta el presupuesto total de la busqueda (aprox. 77-99 corridas de
entrenamiento, diseno: 24 trials x hasta 3 semillas + barridos + compuerta +
control de permutacion + ablacion). El resultado se compara contra
`COST_CEILING_SECONDS` para decidir, de forma explicita, si se procede.
'''

_CODE_COST_FORECAST = '''\
_forecast_t0 = time.time()
_, _forecast_gate_means, _ = entrenar_y_agrupar(
    features=features_with_target, adjacency=A_with, edge_index=edge_index_with,
    feature_mean=feature_mean_with, feature_std=feature_std_with,
    X_past_arr=X_past_with_target, circuito_arr=circuito_past, fid_vano_arr=fid_vano_past,
    alpha=0.2, dropout=0.1, lambda_reconstruction=0.1, lambda_mutual_information=0.1,
    lambda_gate_deviation=0.01, epochs=SEARCH_EPOCHS, seed=SEEDS_SEARCH[0],
)
single_run_seconds = time.time() - _forecast_t0

N_RUNS_LOWER_BOUND = 77
N_RUNS_UPPER_BOUND = 99
projected_lower_seconds = single_run_seconds * N_RUNS_LOWER_BOUND
projected_upper_seconds = single_run_seconds * N_RUNS_UPPER_BOUND

print(f"Una corrida gated de dos pasadas (epochs={SEARCH_EPOCHS}): "
      f"{single_run_seconds:.2f}s ({format_duration(single_run_seconds)})")
print(f"Proyeccion para {N_RUNS_LOWER_BOUND}-{N_RUNS_UPPER_BOUND} corridas: "
      f"{format_duration(projected_lower_seconds)} a {format_duration(projected_upper_seconds)}")
print(f"Techo declarado (COST_CEILING_SECONDS): {format_duration(COST_CEILING_SECONDS)}")

PROCEED_WITH_FULL_SEARCH = projected_upper_seconds <= COST_CEILING_SECONDS
if PROCEED_WITH_FULL_SEARCH:
    print("GO: la proyeccion cabe dentro del techo declarado -- se procede con la busqueda completa.")
else:
    print("NO-GO: la proyeccion EXCEDE el techo declarado -- se usan hiperparametros de "
          "respaldo fijos en vez de lanzar la busqueda completa de Optuna.")
'''

_MD_SEARCH = '''\
## 7. Busqueda de hiperparametros con Optuna (objetivo: ARI cruzada entre semillas)

Maximiza el ARI promedio por pares entre `SEEDS_SEARCH`, sujeto a
`reconstruction_loss_raw <= tau` (diseno: "Optuna objective (implementation)").
Ni la reconstruccion sola ni un criterio que toque `UITI_VANO` futuro entran
jamas al objetivo.
'''

_CODE_SEARCH = '''\
FALLBACK_PARAMS = {
    "lr": 1e-3, "weight_decay": 1e-5, "dropout": 0.1, "optimizer_name": "adamw",
    "lambda_reconstruction": 0.1, "lambda_mutual_information": 0.1,
    "lambda_gate_deviation": 1e-2, "alpha": 0.2,
}

if PROCEED_WITH_FULL_SEARCH:
    meta = {
        "modality_feature_indices": construir_modalidades_mgcecdl(features_with_target),
        "adjacency": A_with,
        "edge_index": edge_index_with,
        "feature_mean": feature_mean_with,
        "feature_std": feature_std_with,
        "circuito": circuito_past,
        "fid_vano": fid_vano_past,
        "hidden_dim": FIXED_HIDDEN_DIM,
        "embed_dim": FIXED_EMBED_DIM,
        "batch_size": FIXED_BATCH_SIZE,
    }
    objective = construir_objetivo_gated(
        X_past_with_target, meta, tau, seeds=SEEDS_SEARCH, k_search=K_SEARCH, epochs=SEARCH_EPOCHS,
    )
    OPTUNA_DIR = DATA_DIR / "optuna"
    OPTUNA_DIR.mkdir(parents=True, exist_ok=True)
    OPTUNA_JOURNAL_PATH = OPTUNA_DIR / f"mgcecdl_graphgated_nb12_{mode}.journal"
    search_study = run_optuna_study(
        objective, study_name=f"mgcecdl_graphgated_nb12_{mode}",
        storage_path=OPTUNA_JOURNAL_PATH, n_trials=OPTUNA_N_TRIALS, direction="maximize",
    )
    try:
        best_params = search_study.best_params
        print("Mejores hiperparametros (Optuna):", best_params)
    except ValueError:
        print("Ningun trial completo produjo un valor finito; se usan hiperparametros de respaldo.")
        best_params = dict(FALLBACK_PARAMS)
else:
    best_params = dict(FALLBACK_PARAMS)
    print("Busqueda completa omitida (ver compuerta de costo); hiperparametros de respaldo:",
          best_params)
'''

_MD_LAMBDA_SWEEPS = '''\
## 8. Barridos de `lambda_dev` y `lambda_MI`

`lambda_dev` incluye explicitamente `0.0` para que un resultado nulo de
colapso no pueda atribuirse solo al regularizador. `lambda_MI` reporta la
MI NORMALIZADA ALCANZADA, no solo su participacion en la perdida.
'''

_CODE_LAMBDA_DEV_SWEEP = '''\
lambda_dev_gate_means = {}
for lambda_dev_value in LAMBDA_DEV_CHOICES:
    _, gate_means_ld, _ = entrenar_y_agrupar(
        features=features_with_target, adjacency=A_with, edge_index=edge_index_with,
        feature_mean=feature_mean_with, feature_std=feature_std_with,
        X_past_arr=X_past_with_target, circuito_arr=circuito_past, fid_vano_arr=fid_vano_past,
        alpha=best_params["alpha"], dropout=best_params["dropout"],
        lambda_reconstruction=best_params["lambda_reconstruction"],
        lambda_mutual_information=best_params["lambda_mutual_information"],
        lambda_gate_deviation=lambda_dev_value, epochs=LAMBDA_SWEEP_EPOCHS, seed=SEEDS_SEARCH[0],
    )
    lambda_dev_gate_means[lambda_dev_value] = gate_means_ld

lambda_dev_summary = resumen_barrido_lambda_dev(lambda_dev_gate_means)
print(lambda_dev_summary)
'''

_CODE_LAMBDA_MI_SWEEP = '''\
lambda_mi_results = {}
for lambda_mi_value in LAMBDA_MI_CHOICES:
    result_mi, _, _ = entrenar_y_agrupar(
        features=features_with_target, adjacency=A_with, edge_index=edge_index_with,
        feature_mean=feature_mean_with, feature_std=feature_std_with,
        X_past_arr=X_past_with_target, circuito_arr=circuito_past, fid_vano_arr=fid_vano_past,
        alpha=best_params["alpha"], dropout=best_params["dropout"],
        lambda_reconstruction=best_params["lambda_reconstruction"],
        lambda_mutual_information=lambda_mi_value,
        lambda_gate_deviation=best_params["lambda_gate_deviation"],
        epochs=LAMBDA_SWEEP_EPOCHS, seed=SEEDS_SEARCH[0],
    )
    lambda_mi_results[lambda_mi_value] = result_mi

lambda_mi_summary = resumen_barrido_lambda_mi(lambda_mi_results)
print(lambda_mi_summary)
'''

_MD_SEED_DISCLOSURE = '''\
## 9. Divulgacion de cuarentena de semillas (diseno D3)

Este cuaderno hace visible, sin ambiguedad, que las semillas de busqueda y
las semillas de la compuerta de aceptacion son conjuntos DISJUNTOS.
'''

_CODE_SEED_DISCLOSURE = '''\
print(f"Semillas de BUSQUEDA (Optuna, cuarentenadas): {SEEDS_SEARCH}")
print(f"Semillas de la COMPUERTA de aceptacion (disjuntas de las de busqueda): {SEEDS_GATE}")
print(f"K_SEARCH={K_SEARCH} es una constante de tiempo de busqueda (search-time constant) "
      "unicamente -- el objetivo de Optuna nunca devuelve un 'K'.")
assert set(SEEDS_SEARCH).isdisjoint(SEEDS_GATE), "las semillas de busqueda y de compuerta deben ser disjuntas."
'''

_MD_ACCEPTANCE_GATE = '''\
## 10. Compuerta de aceptacion anti-colapso (4 criterios, `SEEDS_GATE`)

1. Sin colapso (varianza / rango efectivo, `estadistico_colapso`).
2. ARI estable entre semillas de la compuerta (disjuntas de la busqueda).
3. Supera al control de permutacion que preserva grado (`ejecutar_control_permutacion_grados`).
4. Supera a la linea base sin grafo en asociacion con `UITI_VANO` futuro (`asociacion_criticidad`).

Si CUALQUIER criterio falla, se reporta honestamente que el mecanismo de
gates es decorativo en esta corrida y se envia igualmente la agrupacion del
brazo baseline como resultado utilizable -- la compuerta nunca aborta el
cuaderno.
'''

_CODE_ACCEPTANCE_GATE = '''\
gate_means_by_seed = {}
vano_index_gate = None
for seed in SEEDS_GATE:
    _, gate_means_g, vano_index_g = entrenar_y_agrupar(
        features=features_with_target, adjacency=A_with, edge_index=edge_index_with,
        feature_mean=feature_mean_with, feature_std=feature_std_with,
        X_past_arr=X_past_with_target, circuito_arr=circuito_past, fid_vano_arr=fid_vano_past,
        alpha=best_params["alpha"], dropout=best_params["dropout"],
        lambda_reconstruction=best_params["lambda_reconstruction"],
        lambda_mutual_information=best_params["lambda_mutual_information"],
        lambda_gate_deviation=best_params["lambda_gate_deviation"],
        epochs=GATE_EPOCHS, seed=seed, lr=best_params["lr"],
        weight_decay=best_params["weight_decay"], optimizer_name=best_params["optimizer_name"],
    )
    gate_means_by_seed[seed] = gate_means_g
    if vano_index_gate is None:
        vano_index_gate = vano_index_g

k_datos_result = seleccionar_k_datos(gate_means_by_seed[SEEDS_GATE[0]])
k_raw = k_datos_result["k_raw"]
print(f"K derivado de los datos (silueta + ARI cruzada, nunca forzado): k_raw={k_raw}")

if k_raw > 1:
    gate_cluster_labels_by_seed = {
        seed: KMeans(n_clusters=k_raw, n_init=10, random_state=seed).fit(gm).labels_
        for seed, gm in gate_means_by_seed.items()
    }
else:
    gate_cluster_labels_by_seed = {
        seed: np.zeros(gm.shape[0], dtype=int) for seed, gm in gate_means_by_seed.items()
    }
real_labels_reference = gate_cluster_labels_by_seed[SEEDS_GATE[0]]

# Criterio 1: sin colapso.
colapso_stats = estadistico_colapso(gate_means_by_seed[SEEDS_GATE[0]])
criterio_1_no_colapsado = not colapso_stats["is_collapsed"]

# Criterio 2: ARI cruzada entre semillas de la compuerta (nunca las de busqueda).
criterio_2_ari = mean_pairwise_ari(list(gate_cluster_labels_by_seed.values()))
criterio_2_estable = bool(np.isfinite(criterio_2_ari)) and criterio_2_ari > ARI_STABILITY_THRESHOLD


def _permutation_model_builder(adjacency, edge_index):
    return build_model(features_with_target, adjacency, edge_index,
                        alpha=best_params["alpha"], dropout=best_params["dropout"])


def _permutation_loss_builder():
    return build_loss(feature_mean_with, feature_std_with, A_with,
                       lambda_reconstruction=best_params["lambda_reconstruction"],
                       lambda_mutual_information=best_params["lambda_mutual_information"],
                       lambda_gate_deviation=best_params["lambda_gate_deviation"])


real_silhouette = (
    silhouette_score(gate_means_by_seed[SEEDS_GATE[0]], real_labels_reference) if k_raw > 1 else float("nan")
)
permutation_silhouettes = []
for seed in SEEDS_GATE:
    permutation_result = ejecutar_control_permutacion_grados(
        A_with, features_with_target, _permutation_model_builder, _permutation_loss_builder,
        X_past_with_target, seed, epochs=GATE_EPOCHS, lr=best_params["lr"],
        weight_decay=best_params["weight_decay"], optimizer_name=best_params["optimizer_name"],
        device=DEVICE,
    )
    permuted_model = permutation_result["model"]
    permuted_model.eval()
    with torch.no_grad():
        permuted_input = torch.as_tensor(X_past_with_target, dtype=torch.float32).to(DEVICE)
        permuted_gates = permuted_model(permuted_input)["edge_gates"].cpu().numpy()
    permuted_gate_means, _ = agrupar_gates_por_vano(permuted_gates, circuito_past, fid_vano_past)
    if k_raw > 1:
        permuted_labels = KMeans(n_clusters=k_raw, n_init=10, random_state=seed).fit(permuted_gate_means).labels_
        permutation_silhouettes.append(silhouette_score(permuted_gate_means, permuted_labels))

criterio_3_supera_control = bool(
    np.isfinite(real_silhouette) and permutation_silhouettes
    and real_silhouette > float(np.mean(permutation_silhouettes))
)

# Criterio 4: supera a la linea base sin grafo en asociacion con UITI_VANO futuro.
baseline_labels, baseline_vano_index = linea_base_sin_grafo(
    X_past_with_target, features_with_target, circuito_past, fid_vano_past,
    k=k_raw if k_raw > 1 else 2, seed=SEEDS_GATE[0],
)
future_uiti = uiti_futuro_por_vano(df_identidad, future_mask)

merged_gate = vano_index_gate.assign(cluster=real_labels_reference).merge(
    future_uiti, on=["CIRCUITO", "FID_VANO"], how="inner"
)
merged_baseline = baseline_vano_index.assign(cluster=baseline_labels).merge(
    future_uiti, on=["CIRCUITO", "FID_VANO"], how="inner"
)


def _epsilon_squared_or_none(frame):
    if frame["cluster"].nunique() < 2:
        return None
    stats = asociacion_criticidad(frame["cluster"].to_numpy(), frame["UITI_VANO_futuro_acumulado"].to_numpy())
    return stats["epsilon_squared"]


epsilon_gate = _epsilon_squared_or_none(merged_gate)
epsilon_baseline = _epsilon_squared_or_none(merged_baseline)
criterio_4_supera_baseline = (
    epsilon_gate is not None and epsilon_baseline is not None and epsilon_gate > epsilon_baseline
)

acceptance_criteria = {
    "1_no_colapsado": criterio_1_no_colapsado,
    "2_ari_estable": criterio_2_estable,
    "3_supera_control_permutacion": criterio_3_supera_control,
    "4_supera_baseline_sin_grafo": criterio_4_supera_baseline,
}
GATE_PASS = all(acceptance_criteria.values())
print("Criterios de aceptacion:", acceptance_criteria)

if GATE_PASS:
    print("Compuerta anti-colapso APROBADA: el mecanismo de gates aporta senal real.")
    FINAL_CLUSTER_SOURCE = "gated"
    final_cluster_labels = real_labels_reference
    final_vano_index = vano_index_gate
else:
    print(
        "Compuerta anti-colapso NO aprobada: al menos un criterio fallo. Se reporta "
        "honestamente que el mecanismo de gates es DECORATIVE en esta corrida y se envia "
        "la agrupacion del brazo baseline (sin grafo) como resultado utilizable -- la "
        "compuerta nunca aborta el cuaderno."
    )
    FINAL_CLUSTER_SOURCE = "baseline"
    final_cluster_labels = baseline_labels
    final_vano_index = baseline_vano_index
'''

_MD_EDGE_DEVIATION = '''\
## 11. Tabla de desviacion por arista y proyeccion UMAP 2D

La tabla colapsa cadenas de rezago intra-familia climatica en tiempo de
ejecucion (`CLIMATE_FAMILIES`). La proyeccion UMAP reutiliza el estilo visual
de la libreta 11 (barra de color horizontal, limites robustos p2-p98, ticks
en unidades originales).
'''

_CODE_EDGE_DEVIATION = '''\
edge_deviation_table = tabla_desviacion_aristas(
    gate_means_by_seed[SEEDS_GATE[0]], edge_index_with, real_labels_reference, colapsar_familias=True,
)
print(edge_deviation_table.head(15))
'''

_CODE_UMAP = '''\
import matplotlib.pyplot as plt
import umap
from matplotlib.colors import BoundaryNorm, ListedColormap


def add_horizontal_colorbar(fig, ax, mappable, label, ticks=None, tick_labels=None):
    # Barra horizontal DEBAJO del panel, posicionada midiendo la extension real ya
    # renderizada -- mismo patron que la libreta 11.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    to_figure_coords = fig.transFigure.inverted()
    panel_box = ax.get_position()
    panel_bottom = to_figure_coords.transform(ax.get_tightbbox(renderer))[0][1]
    bar_height = 0.022
    bar_y = max(panel_bottom - 0.055 - bar_height, 0.02)
    cax = fig.add_axes([panel_box.x0, bar_y, panel_box.width, bar_height])
    colorbar = fig.colorbar(mappable, cax=cax, orientation="horizontal")
    if ticks is not None:
        colorbar.set_ticks(ticks)
        if tick_labels is not None:
            colorbar.set_ticklabels(tick_labels)
    colorbar.set_label(label)
    return colorbar


def robust_color_limits(values, low=2.0, high=98.0):
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, None
    vmin, vmax = np.percentile(finite, [low, high])
    if vmin == vmax:
        return None, None
    return float(vmin), float(vmax)


def log_ticks_in_original_units(log_vmin, log_vmax, max_ticks=8):
    if log_vmin is None or log_vmax is None:
        return None, None
    candidates = sorted(
        {mantissa * (10.0 ** exponent)
         for exponent in range(int(np.floor(log_vmin)), int(np.ceil(log_vmax)) + 1)
         for mantissa in (1, 2, 5)}
    )
    inside = [v for v in candidates if log_vmin <= np.log10(v) <= log_vmax]
    if not inside:
        inside = [10.0 ** log_vmin, 10.0 ** log_vmax]
    if len(inside) > max_ticks:
        inside = inside[:: int(np.ceil(len(inside) / max_ticks))]
    labels = [f"{v:,.0f}" if v >= 1 else f"{v:g}" for v in inside]
    return np.log10(inside), labels


umap_frame = vano_index_gate.copy()
umap_frame["cluster"] = real_labels_reference
umap_frame = umap_frame.merge(future_uiti, on=["CIRCUITO", "FID_VANO"], how="left")
has_aggregates = umap_frame["UITI_VANO_futuro_acumulado"].notna().to_numpy()

n_vanos_gate = gate_means_by_seed[SEEDS_GATE[0]].shape[0]
if n_vanos_gate < 5:
    print(f"Solo {n_vanos_gate} vanos: se omite la proyeccion UMAP (necesita >= 5).")
else:
    reducer = umap.UMAP(n_components=2, random_state=RANDOM_STATE)
    umap_2d = reducer.fit_transform(gate_means_by_seed[SEEDS_GATE[0]])

    cluster_values = umap_frame["cluster"].to_numpy()
    cluster_ids = np.unique(cluster_values)
    point_size = 6.0 if n_vanos_gate > 5000 else 12.0

    fig, axes = plt.subplots(1, 3, figsize=(16.5, 6.0))
    fig.subplots_adjust(left=0.05, right=0.98, bottom=0.26, top=0.88, wspace=0.18)

    cluster_cmap = ListedColormap(plt.get_cmap("tab10").colors[: len(cluster_ids)])
    cluster_norm = BoundaryNorm(np.arange(len(cluster_ids) + 1) - 0.5, len(cluster_ids))
    scatter_clusters = axes[0].scatter(
        umap_2d[:, 0], umap_2d[:, 1], c=cluster_values, cmap=cluster_cmap, norm=cluster_norm,
        s=point_size, alpha=0.75, linewidths=0,
    )
    axes[0].set_title(f"Clusters (K derivado de los datos = {k_raw})")

    uiti_values = umap_frame["UITI_VANO_futuro_acumulado"].to_numpy()
    log_uiti = np.log10(np.clip(np.nan_to_num(uiti_values, nan=1e-6), 1e-6, None))
    uiti_vmin, uiti_vmax = robust_color_limits(log_uiti[has_aggregates])
    scatter_uiti = axes[1].scatter(
        umap_2d[has_aggregates, 0], umap_2d[has_aggregates, 1],
        c=log_uiti[has_aggregates], cmap="viridis", vmin=uiti_vmin, vmax=uiti_vmax,
        s=point_size, alpha=0.75, linewidths=0,
    )
    axes[1].set_title("UITI_VANO futuro acumulado por vano")

    eventos_values = umap_frame["n_eventos_futuro"].to_numpy()
    log_eventos = np.log10(np.clip(np.nan_to_num(eventos_values, nan=1.0), 1.0, None))
    eventos_vmin, eventos_vmax = robust_color_limits(log_eventos[has_aggregates])
    scatter_eventos = axes[2].scatter(
        umap_2d[has_aggregates, 0], umap_2d[has_aggregates, 1],
        c=log_eventos[has_aggregates], cmap="magma", vmin=eventos_vmin, vmax=eventos_vmax,
        s=point_size, alpha=0.75, linewidths=0,
    )
    axes[2].set_title("Numero de eventos futuros por vano")

    for ax in axes:
        ax.set_xlabel("UMAP 1")
        ax.set_ylabel("UMAP 2")
        ax.set_xticklabels([])
        ax.set_yticklabels([])

    fig.suptitle(f"Proyeccion UMAP 2D de los gates por vano (n={n_vanos_gate}, mode={mode})", fontsize=13)

    uiti_ticks, uiti_tick_labels = log_ticks_in_original_units(uiti_vmin, uiti_vmax)
    eventos_ticks, eventos_tick_labels = log_ticks_in_original_units(eventos_vmin, eventos_vmax)
    add_horizontal_colorbar(fig, axes[0], scatter_clusters, "Cluster",
                            ticks=cluster_ids, tick_labels=[str(c) for c in cluster_ids])
    add_horizontal_colorbar(fig, axes[1], scatter_uiti, "UITI_VANO futuro (color log, p2-p98)",
                            ticks=uiti_ticks, tick_labels=uiti_tick_labels)
    add_horizontal_colorbar(fig, axes[2], scatter_eventos, "Eventos futuros (color log, p2-p98)",
                            ticks=eventos_ticks, tick_labels=eventos_tick_labels)

    UMAP_FIGURE_PATH = FIGURES_DIR / f"mgcecdl_graphgated_nb12_{mode}_umap_gates.png"
    fig.savefig(UMAP_FIGURE_PATH, dpi=150)
    print("Figura:", UMAP_FIGURE_PATH)
    plt.show()
'''

_MD_ABLATION = '''\
## 12. Ablacion: con vs. sin `UITI_VANO` reinyectada

Repite el entrenamiento sobre el brazo SIN `UITI_VANO` (`X_past_without_target`,
`edge_index_without`) para aislar cuanto de la asociacion observada es mera
persistencia versus senal aportada por la reinyeccion del target.
'''

_CODE_ABLATION = '''\
ablation_gate_means_by_seed = {}
vano_index_ablation = None
for seed in SEEDS_SEARCH:
    _, gate_means_wo, vano_index_wo = entrenar_y_agrupar(
        features=features_without_target, adjacency=A_without, edge_index=edge_index_without,
        feature_mean=feature_mean_without, feature_std=feature_std_without,
        X_past_arr=X_past_without_target, circuito_arr=circuito_past, fid_vano_arr=fid_vano_past,
        alpha=best_params["alpha"], dropout=best_params["dropout"],
        lambda_reconstruction=best_params["lambda_reconstruction"],
        lambda_mutual_information=best_params["lambda_mutual_information"],
        lambda_gate_deviation=best_params["lambda_gate_deviation"],
        epochs=ABLATION_EPOCHS, seed=seed,
    )
    ablation_gate_means_by_seed[seed] = gate_means_wo
    if vano_index_ablation is None:
        vano_index_ablation = vano_index_wo

k_ablation = k_raw if k_raw > 1 else 2
ablation_labels = KMeans(
    n_clusters=k_ablation, n_init=10, random_state=SEEDS_SEARCH[0]
).fit(ablation_gate_means_by_seed[SEEDS_SEARCH[0]]).labels_
merged_ablation = vano_index_ablation.assign(cluster=ablation_labels).merge(
    future_uiti, on=["CIRCUITO", "FID_VANO"], how="inner"
)
epsilon_sin_uiti_vano = _epsilon_squared_or_none(merged_ablation)

print("Ablacion (sin UITI_VANO reinyectada):")
print(f"  epsilon^2 (sin UITI_VANO)  = {epsilon_sin_uiti_vano}")
print(f"  epsilon^2 (con UITI_VANO)  = {epsilon_gate}")
if epsilon_sin_uiti_vano is not None and epsilon_gate is not None:
    print(f"  delta (con - sin)          = {epsilon_gate - epsilon_sin_uiti_vano:.6f}")
'''

_MD_PROXY_GUARD = '''\
## 13. Guardia de proxy univariante

Para CADA feature (incluida `UITI_VANO` explicitamente) se ajusta un
`KMeans` 1-D y se compara su ARI contra los clusters de gates. `max_f ARI >
0.8` invalida (voids) el resultado.
'''

_CODE_PROXY_GUARD = '''\
X_vano_means, _ = agrupar_gates_por_vano(X_past_with_target, circuito_past, fid_vano_past)
proxy_guard_table = guardia_proxy_univariante(
    real_labels_reference, X_vano_means, features_with_target,
    k=k_raw if k_raw > 1 else 2, seed=SEEDS_GATE[0],
)
print(proxy_guard_table.head(10))
print("voided:", proxy_guard_table.attrs["voided"], "| max_ari:", proxy_guard_table.attrs["max_ari"])
if "uiti_vano_ari" in proxy_guard_table.attrs:
    print("ARI de UITI_VANO en solitario:", proxy_guard_table.attrs["uiti_vano_ari"])
if proxy_guard_table.attrs["voided"]:
    print("GUARDIA DE PROXY DISPARADA: una sola variable reproduce la agrupacion "
          "(ARI > umbral); el resultado se marca void.")
'''

_MD_NO_GRAPH_BASELINE = '''\
## 14. Linea base sin grafo (obligatoria)

`KMeans` sobre la media por vano de las features crudas ESTANDARIZADAS,
usando el mismo protocolo de K y semilla que el brazo con gates -- ya
calculada como parte de la compuerta de aceptacion (criterio 4).
'''

_CODE_NO_GRAPH_BASELINE = '''\
print(f"Linea base sin grafo: K={k_raw if k_raw > 1 else 2} | "
      f"n_vanos={len(baseline_vano_index)} | "
      f"epsilon^2 (baseline) = {epsilon_baseline}")
'''

_MD_K_DATA_DRIVEN = '''\
## 15. K derivado de los datos y vista operativa de 3-4 niveles

`k_raw` nunca se sustituye silenciosamente. La vista de 3-4 niveles es un
paso EXPLICITO y separado que ordena los clusters por criticidad futura
MEDIANA -- solo para reporte, jamas realimentada al entrenamiento ni a la
compuerta de aceptacion.
'''

_CODE_K_DATA_DRIVEN = '''\
print(f"K bruto (derivado de los datos, nunca forzado): k_raw={k_raw}")
if k_raw >= 3:
    cluster_median_criticality = (
        merged_gate.groupby("cluster")["UITI_VANO_futuro_acumulado"].median().sort_values()
    )
    ordered_clusters = list(cluster_median_criticality.index)
    n_tiers = 4 if k_raw >= 4 else 3
    tier_bins = np.array_split(ordered_clusters, n_tiers)
    cluster_to_tier = {
        cluster: tier_index
        for tier_index, bin_clusters in enumerate(tier_bins)
        for cluster in bin_clusters
    }
    tier_view = merged_gate.assign(tier=merged_gate["cluster"].map(cluster_to_tier))
    print(f"Vista operativa derivada de {n_tiers} niveles (nunca sustituye a k_raw={k_raw}):")
    print(tier_view.groupby("tier")["UITI_VANO_futuro_acumulado"].agg(["count", "median"]))
else:
    tier_view = None
    print(f"k_raw={k_raw} < 3: se reporta honestamente sin forzar una vista de 3-4 niveles.")
'''

_MD_KRUSKAL = '''\
## 16. Asociacion cluster vs. criticidad futura (Kruskal-Wallis + epsilon^2 + Dunn-BH)

Reutiliza `asociacion_criticidad` (PR2) -- Kruskal-Wallis, tamano de efecto
`epsilon^2`, y post-hoc de Dunn con correccion Benjamini-Hochberg. No se
reimplementa ninguna de estas pruebas aqui.
'''

_CODE_KRUSKAL = '''\
if merged_gate["cluster"].nunique() >= 2:
    criticidad_stats = asociacion_criticidad(
        merged_gate["cluster"].to_numpy(), merged_gate["UITI_VANO_futuro_acumulado"].to_numpy()
    )
    print(f"Kruskal-Wallis H={criticidad_stats['H']:.4f} p={criticidad_stats['p_value']:.4g} "
          f"epsilon^2={criticidad_stats['epsilon_squared']:.4f} (n={criticidad_stats['n']}, "
          f"k={criticidad_stats['k']})")
    print(criticidad_stats["pairwise"])
else:
    print("Menos de 2 clusters con datos futuros disponibles: no se evalua Kruskal-Wallis.")
'''

_MD_PERSISTENCE = '''\
## 17. Diagnostico de persistencia: correlacion de CONTEO de eventos (secundaria)

`UITI_VANO` futuro acumulado es la metrica PRIMARIA (seccion 16). El CONTEO
de eventos es secundario; su correlacion pasado-futuro se reporta junto con
las tres explicaciones candidatas (`diagnostico_persistencia`, diseno D8):
regresion a la media, intervencion de CHEC (por `COD_CAUSA`), y censura.
Se reutiliza `diagnostico_persistencia` sumando una columna unitaria por
evento, de forma que la suma agregada por vano ES el conteo.
'''

_CODE_PERSISTENCE = '''\
df_identidad_evento_unitario = df_identidad.copy()
df_identidad_evento_unitario["EVENTO_UNITARIO"] = 1
diagnostico_eventos = diagnostico_persistencia(
    df_identidad_evento_unitario, past_mask, future_mask, target="EVENTO_UNITARIO",
)

print(f"Correlacion pasado-futuro (CONTEO de eventos, metrica secundaria): "
      f"{diagnostico_eventos['primary_correlation_both_windows']:.4f} "
      f"(n_vanos={diagnostico_eventos['n_vanos_both_windows']})")
print(f"  Explicacion 1 -- regresion a la media (intra-pasado): "
      f"{diagnostico_eventos['regression_to_mean_correlation']:.4f}")
print(f"  Explicacion 2 -- intervencion CHEC por COD_CAUSA:")
print(diagnostico_eventos["intervention_by_cod_causa"])
print(f"  Explicacion 3 -- censura (sin restriccion de presencia en ambas ventanas): "
      f"{diagnostico_eventos['censoring_correlation_unrestricted']:.4f} "
      f"(n_vanos={diagnostico_eventos['n_vanos_unrestricted']})")
'''

_MD_SEASONAL_LIMITATION = '''\
## 18. Limitacion: confusion estacional y techo interpretativo honesto

El dataset abarca `2025-11-01` a `2026-04-30`: la ventana futura de
validacion son apenas ~2 meses de una unica estacion. Esta particion no
puede separar el efecto del TIEMPO del efecto de la ESTACION con solo seis
meses de datos -- cualquier lectura de "mejora futura" o "deterioro futuro"
debe leerse con esta confusion presente, junto a cada resultado de la
ventana futura reportado arriba.

**Techo interpretativo honesto.** El payload fisico del grafo experto es
reducido: unos pocos acoplamientos base, algo mas al incluir las variables
recuperadas por la seleccion nb12-local. Este cuaderno NO reclama haber
recuperado la estructura fisica completa de la red de distribucion -- los
gates aprendidos son, en el mejor de los casos, una re-ponderacion por
muestra sobre un esqueleto de grafo deliberadamente pequeno.
'''

_MD_SUMMARY = '''\
## 19. Resumen final

Se reportan, en una sola tabla, las cantidades que este cuaderno DERIVA en
tiempo de ejecucion (nunca literales): `p`/`E` por brazo, las features de
grado 0, la MI normalizada alcanzada, la varianza de gates frente a
`lambda_dev`, y la fecha de corte p70.
'''

_CODE_SUMMARY = '''\
resumen_final = {
    "mode": mode,
    "p_con_uiti_vano": len(features_with_target),
    "E_con_uiti_vano": edge_index_with.n_edges,
    "p_sin_uiti_vano": len(features_without_target),
    "E_sin_uiti_vano": edge_index_without.n_edges,
    "features_grado_cero": ungatable,
    "fecha_corte_p70": str(fecha_corte),
    "tau": tau,
    "k_raw": k_raw,
    "acceptance_criteria": acceptance_criteria,
    "gate_pass": GATE_PASS,
    "final_cluster_source": FINAL_CLUSTER_SOURCE,
    "epsilon_squared_con_uiti_vano": epsilon_gate,
    "epsilon_squared_sin_uiti_vano": epsilon_sin_uiti_vano,
    "epsilon_squared_baseline_sin_grafo": epsilon_baseline,
    "correlacion_conteo_eventos_pasado_futuro": diagnostico_eventos["primary_correlation_both_windows"],
    "proxy_guard_voided": bool(proxy_guard_table.attrs["voided"]),
}
for key, value in resumen_final.items():
    print(f"{key}: {value}")
'''


def _cell(kind: str, source: str, *, tags: list[str] | None = None) -> nbformat.NotebookNode:
    if kind == "markdown":
        return new_markdown_cell(source)
    cell = new_code_cell(source)
    if tags:
        cell["metadata"]["tags"] = list(tags)
    return cell


def build_notebook() -> nbformat.NotebookNode:
    """Assemble the (unexecuted) notebook-12 skeleton -- pure, no training."""
    cells = [
        _cell("markdown", _MD_TITLE),
        _cell("markdown", _MD_DIAGRAM),
        _cell("code", _CODE_PARAMETERS, tags=["parameters"]),
        _cell("markdown", _MD_BOOTSTRAP),
        _cell("code", _CODE_BOOTSTRAP),
        _cell("code", _CODE_IMPORTS),
        _cell("markdown", _MD_CONFIG),
        _cell("code", _CODE_CONFIG),
        _cell("markdown", _MD_DATA_LOAD),
        _cell("code", _CODE_DATA_LOAD),
        _cell("markdown", _MD_GRAPH),
        _cell("code", _CODE_GRAPH),
        _cell("markdown", _MD_SPLIT),
        _cell("code", _CODE_SPLIT),
        _cell("markdown", _MD_HELPERS),
        _cell("code", _CODE_HELPERS),
        _cell("markdown", _MD_TAU),
        _cell("code", _CODE_TAU),
        _cell("markdown", _MD_COST_FORECAST),
        _cell("code", _CODE_COST_FORECAST),
        _cell("markdown", _MD_SEARCH),
        _cell("code", _CODE_SEARCH),
        _cell("markdown", _MD_LAMBDA_SWEEPS),
        _cell("code", _CODE_LAMBDA_DEV_SWEEP),
        _cell("code", _CODE_LAMBDA_MI_SWEEP),
        _cell("markdown", _MD_SEED_DISCLOSURE),
        _cell("code", _CODE_SEED_DISCLOSURE),
        _cell("markdown", _MD_ACCEPTANCE_GATE),
        _cell("code", _CODE_ACCEPTANCE_GATE),
        _cell("markdown", _MD_EDGE_DEVIATION),
        _cell("code", _CODE_EDGE_DEVIATION),
        _cell("code", _CODE_UMAP),
        _cell("markdown", _MD_ABLATION),
        _cell("code", _CODE_ABLATION),
        _cell("markdown", _MD_PROXY_GUARD),
        _cell("code", _CODE_PROXY_GUARD),
        _cell("markdown", _MD_NO_GRAPH_BASELINE),
        _cell("code", _CODE_NO_GRAPH_BASELINE),
        _cell("markdown", _MD_K_DATA_DRIVEN),
        _cell("code", _CODE_K_DATA_DRIVEN),
        _cell("markdown", _MD_KRUSKAL),
        _cell("code", _CODE_KRUSKAL),
        _cell("markdown", _MD_PERSISTENCE),
        _cell("code", _CODE_PERSISTENCE),
        _cell("markdown", _MD_SEASONAL_LIMITATION),
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
                "every feature/edge dimension must be derived at runtime."
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
        "--out", type=Path, default=NOTEBOOK_12_PATH,
        help="Output path for the generated notebook (defaults to notebooks/project_flow/12_*.ipynb).",
    )
    args = parser.parse_args()

    notebook = generate(args.out)
    print(f"Notebook 12 written to {args.out} ({len(notebook.cells)} cells).")


if __name__ == "__main__":
    main()
