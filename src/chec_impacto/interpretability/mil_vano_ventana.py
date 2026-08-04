"""Validation harness for the bag-level MIL regressor over 01.4's vano x
window bags (`chec_impacto.models.mgcecdl_mil.MILBagRegressor`).

Primary CV is `StratifiedGroupKFold(groups=CIRCUITO|FID_VANO)` -- the same
composite key `chec_impacto.data.bags.BagIndex.group` already carries -- so
no vano's bags ever cross a fold boundary, even under 01.4's overlapping
windows. The headline metric is out-of-fold macro-F1 on the subset of bags
whose vano has >=2 windows AND whose observed 01.4 criticality class is not
constant across them (`subconjunto_variacion_intravano`, computed ONCE on
observed labels before CV and frozen). Three baselines -- majority,
structural-only/no-climate, and persistence -- are scored on the identical
subset (`baseline_mayoritaria`, `baseline_estructural`, `baseline_persistencia`).

`persistencia` is deliberately information-advantaged: grouped CV keeps all
of a vano's bags in one fold, so it sees the realized OBSERVED outcomes of
the same vano's other windows, which the model never gets. That is what
makes the pre-registered bar (`BARRA_ACEPTACION_A1_PUNTOS`, a module
constant -- never a caller-supplied parameter, so it cannot be
renegotiated after results are seen) a demanding one: the model must beat
persistence by >= 5.0 points of macro-F1 on the within-vano-variation
subset (`evaluar_arms`). Missing it is reported as a descriptive
characterization plus an explicit negative result -- there is no code path
here that iterates loss terms to chase the bar.

`BagPredictor` adapts a fitted `MILBagRegressor` to bag-level u-hat/class/
proba, and to the two contracts read at source in design D7:
  - `KernelShapTopVarsExtractor` hardcodes `predict_proba_positiva`, which
    returns column 1 whenever `predict_proba` has more than one column
    (`interpretability/circuit_analysis.py:96-99`) -- so `predict_proba`
    here returns exactly 2 columns, `[1 - P(Alto), P(Alto)]`, never the
    full 4-class matrix.
  - the simulator's `predict_fn(model, X, *, device, batch_size) ->
    {"fused_probs": (n, 4), "predicted_classes": (n,)}`
    (`chec_local_interpreter/simulator.py:182-193`). `predict_fn` below
    pins that shape contract; no simulator is built or run here.

See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain
    `mil-validation-protocol`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D7, D8)
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support
from scipy.stats import spearmanr
from sklearn.model_selection import StratifiedGroupKFold

from chec_impacto.interpretability.circuit_analysis import agregar_borda
from chec_impacto.interpretability.mgcecdl_graph import (
    estadistico_colapso,
    grafo_reconstruido_por_grupo,
    guardia_proxy_univariante,
)
from chec_impacto.models.criticality_assignment import (
    GRUPOS,
    Geometria,
    asignar_clase,
    distribucion_suave,
)

# Pre-registered, non-renegotiable (spec `mil-validation-protocol`, A1): the model must
# beat the persistence baseline by AT LEAST this many points of macro-F1 on the
# within-vano-variation subset to claim a positive result. A module constant that no
# caller can override -- deliberately absent from every function signature below.
BARRA_ACEPTACION_A1_PUNTOS = 5.0


# ---------------------------------------------------------------------------
# Generic pooling utility (D8: "Extended, as new code")
# ---------------------------------------------------------------------------


def agrupar_por_claves(values: np.ndarray, keys: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    """Generic groupby-mean over arbitrary key columns.

    `agrupar_gates_por_vano` (`interpretability/mgcecdl_graph.py:108`) is
    hardcoded to `["CIRCUITO", "FID_VANO"]`; this is the generalization D8
    needs for bag-grain reporting, which additionally carries a `VENTANA`
    key.
    """
    values = np.asarray(values)
    if values.ndim != 2:
        raise ValueError(f"values must be 2-D (n_rows, n_dims); got shape {values.shape}.")

    keys_df = pd.DataFrame(keys).reset_index(drop=True)
    if len(keys_df) != values.shape[0]:
        raise ValueError("keys must have the same number of rows as values.")

    key_cols = list(keys_df.columns)
    value_frame = pd.DataFrame(values, columns=[f"dim_{i}" for i in range(values.shape[1])])
    frame = pd.concat([keys_df.reset_index(drop=True), value_frame], axis=1)

    grouped = frame.groupby(key_cols, sort=False).mean()
    pooled_values = grouped.to_numpy()
    key_index = grouped.index.to_frame(index=False).reset_index(drop=True)
    return pooled_values, key_index


# ---------------------------------------------------------------------------
# Frozen within-vano-variation subset + grouped CV
# ---------------------------------------------------------------------------


def subconjunto_variacion_intravano(bag_index: Any, clase_observada: np.ndarray) -> np.ndarray:
    """Boolean mask (n_bags,), True for bags of vanos with >=2 windows whose
    OBSERVED 01.4 class is not constant across those windows.

    Computed ONCE on observed labels and `bag_index.group` (the vano
    identity) -- never on any fold-dependent quantity, so it is safe to
    compute a single time before CV and reuse for every fold (spec:
    "the within-variation mask is computed once and never recomputed per
    fold").
    """
    clase_observada = np.asarray(clase_observada).reshape(-1)
    group = np.asarray(bag_index.group)
    if clase_observada.shape[0] != group.shape[0]:
        raise ValueError("clase_observada must have one entry per bag in bag_index.")

    frame = pd.DataFrame({"group": group, "clase": clase_observada})
    n_windows = frame.groupby("group")["clase"].transform("size")
    n_unique = frame.groupby("group")["clase"].transform("nunique")
    mask = (n_windows >= 2) & (n_unique >= 2)
    return mask.to_numpy(dtype=bool)


def construir_folds_agrupados(
    bag_index: Any,
    clase_observada: np.ndarray,
    *,
    n_splits: int = 5,
    seed: int = 42,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Primary CV (D8): `StratifiedGroupKFold(groups=bag_index.group)`.

    `bag_index.group` is already the composite `f"{CIRCUITO}|{FID_VANO}"`
    key, so no vano's bags can ever cross a fold boundary -- this is what
    stops the same event row (duplicated across overlapping windows) from
    leaking across folds.
    """
    clase_observada = np.asarray(clase_observada).reshape(-1)
    n_bags = clase_observada.shape[0]
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    X_dummy = np.zeros((n_bags, 1))
    return list(splitter.split(X_dummy, clase_observada, groups=bag_index.group))


# ---------------------------------------------------------------------------
# Three mandatory baselines (D8)
# ---------------------------------------------------------------------------


def baseline_mayoritaria(clase_train: np.ndarray, n_test: int) -> np.ndarray:
    """Majority baseline: the training fold's modal class, broadcast."""
    clase_train = np.asarray(clase_train).reshape(-1)
    if clase_train.size == 0:
        raise ValueError("clase_train must not be empty.")
    valores, conteos = np.unique(clase_train, return_counts=True)
    moda = valores[np.argmax(conteos)]
    return np.full(int(n_test), moda, dtype=clase_train.dtype)


def baseline_estructural(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    n_obs_test: np.ndarray,
    geometria: Geometria,
    *,
    seed: int = 42,
) -> np.ndarray:
    """Structural-only / no-climate baseline: `RandomForestRegressor` on the
    bag's structural-feature means, predicting `log1p(u)`, then the SAME
    nearest-centroid assignment every other arm uses.

    `linea_base_sin_grafo` (`interpretability/mgcecdl_graph.py:140-158`)
    CANNOT serve here (design D8 correction): it emits KMeans cluster ids,
    not criticality classes, and pools through `agrupar_gates_por_vano`,
    whose groupby is hardcoded to `["CIRCUITO", "FID_VANO"]` with no window
    key. This function never imports or calls it.
    """
    X_train = np.asarray(X_train, dtype=np.float64)
    X_test = np.asarray(X_test, dtype=np.float64)
    y_train = np.asarray(y_train, dtype=np.float64).reshape(-1)
    if X_train.shape[0] != y_train.shape[0]:
        raise ValueError("X_train and y_train must have the same number of rows.")

    u_pred = predecir_u_estructural(X_train, y_train, X_test, seed=seed)
    n_obs_test = np.asarray(n_obs_test, dtype=np.float64)
    clase_pred, _ = asignar_clase(n_obs_test, u_pred, geometria)
    return clase_pred


def predecir_u_estructural(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    *,
    seed: int = 42,
) -> np.ndarray:
    """The structural baseline's `û`, before it becomes a class.

    Extracted so the baseline's regression is OBSERVABLE.
    `baseline_estructural` returned the class and discarded `û`, which made
    it impossible to ask where a macro-F1 gap lives: both arms regress the
    same `u` and both pass through the same frozen nearest-centroid rule, so
    the gap is either in the regression or in the mapping -- and comparing
    classes alone cannot separate them.
    """
    X_train = np.asarray(X_train, dtype=np.float64)
    X_test = np.asarray(X_test, dtype=np.float64)
    y_train = np.asarray(y_train, dtype=np.float64).reshape(-1)
    if X_train.shape[0] != y_train.shape[0]:
        raise ValueError("X_train and y_train must have the same number of rows.")

    modelo = RandomForestRegressor(n_estimators=200, random_state=seed)
    modelo.fit(X_train, np.log1p(y_train))
    return np.expm1(modelo.predict(X_test))


def contraste_u(
    y_obs: np.ndarray,
    u_hats: Mapping[str, np.ndarray],
    mask: np.ndarray,
) -> pd.DataFrame:
    """Compare arms in `u` space instead of class space.

    Reported in `log1p` -- the space the model is actually trained on. Raw-`u`
    error would be dominated by the tail and would say almost nothing about
    the bags that decide macro-F1.

    `spearman` separates two failures that class metrics fuse: ranking the
    bags correctly but at the wrong level (high spearman, high MAE) versus
    getting the level roughly right while ordering them badly.
    """
    y_obs = np.asarray(y_obs, dtype=np.float64).reshape(-1)
    mask = np.asarray(mask, dtype=bool)
    objetivo = np.log1p(y_obs[mask])
    n_subset = int(mask.sum())

    filas: list[dict[str, Any]] = []
    for nombre, u_hat in u_hats.items():
        u_hat = np.asarray(u_hat, dtype=np.float64).reshape(-1)
        if u_hat.shape[0] != n_subset:
            raise ValueError(
                f"u_hats[{nombre!r}] tiene {u_hat.shape[0]} entradas pero la mask selecciona "
                f"{n_subset} bolsas; la longitud debe coincidir."
            )
        # log1p no esta definido bajo -1; una prediccion no positiva es un
        # error del modelo, no un motivo para propagar NaN a toda la tabla.
        prediccion = np.log1p(np.maximum(u_hat, 0.0))
        residuo = prediccion - objetivo
        rho = spearmanr(prediccion, objetivo).statistic if n_subset > 1 else float("nan")
        filas.append(
            {
                "arm": nombre,
                "n": n_subset,
                "spearman": float(rho),
                "mae_log1p": float(np.mean(np.abs(residuo))),
                "rmse_log1p": float(np.sqrt(np.mean(residuo**2))),
                "sesgo_log1p": float(np.mean(residuo)),
            }
        )
    return pd.DataFrame(filas)


def baseline_persistencia(
    bag_index: Any,
    clase_observada: np.ndarray,
    test_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Persistence baseline: for each TEST bag of vano `v`, the modal
    OBSERVED class among `v`'s OTHER bags within `test_mask`.

    Deliberately information-advantaged (D8): grouped CV keeps all of a
    vano's bags in one fold, so this baseline is given the realized
    outcomes of the SAME vano's other windows, which the model never gets.
    Single-window vanos (no other bag in `test_mask`) get no prediction;
    `tiene_prediccion[i]` is False for those, and they are excluded from the
    within-variation subset by `subconjunto_variacion_intravano`
    independently, by construction.

    Returns `(predicciones, tiene_prediccion)`, both aligned to the ORDER of
    `np.flatnonzero(test_mask)` (i.e. index `i` corresponds to the `i`-th
    True entry of `test_mask`, in ascending bag-position order).
    """
    clase_observada = np.asarray(clase_observada).reshape(-1)
    test_mask = np.asarray(test_mask, dtype=bool)
    group = np.asarray(bag_index.group)

    test_indices = np.flatnonzero(test_mask)
    frame = pd.DataFrame(
        {"group": group[test_indices], "clase": clase_observada[test_indices]}
    )

    predicciones = np.zeros(len(frame), dtype=clase_observada.dtype)
    tiene_prediccion = np.zeros(len(frame), dtype=bool)

    for _, sub in frame.groupby("group", sort=False):
        posiciones = sub.index.to_numpy()
        if len(posiciones) < 2:
            continue
        for posicion in posiciones:
            otras_clases = sub.loc[sub.index != posicion, "clase"]
            moda = otras_clases.mode().iloc[0]
            predicciones[posicion] = moda
            tiene_prediccion[posicion] = True

    return predicciones, tiene_prediccion


# ---------------------------------------------------------------------------
# Arm evaluation: headline A1 comparison + per-circuit reporting breakdown
# ---------------------------------------------------------------------------


def evaluar_arms(
    clase_obs: np.ndarray,
    predicciones: Mapping[str, np.ndarray],
    mask: np.ndarray,
) -> pd.DataFrame:
    """Out-of-fold macro-F1 for every arm in `predicciones`, on `mask`'s
    subset. When `"modelo"` and at least one other arm are present, attaches
    the A1 pass/fail verdict against `BARRA_ACEPTACION_A1_PUNTOS` as
    `frame.attrs` -- a missed bar is reported as a descriptive
    characterization plus an explicit negative result, never as a trigger to
    keep iterating loss terms in search of the bar (spec
    `mil-validation-protocol`, "Pre-registered +5-point acceptance bar").

    The gate compares the model against the BEST-performing baseline arm
    (`max` macro-F1 over every non-`"modelo"` arm), not against
    `"persistencia"` alone. A no-climate structural-only control that beats
    both the model and persistence must be able to fail the gate; comparing
    only to persistence let exactly that case through undetected. This makes
    A1 strictly harder to pass than before -- tightening an acceptance bar
    after seeing results is legitimate diligence, not goalpost-moving, which
    would mean loosening a bar after an unfavorable result.
    `delta_modelo_vs_persistencia_pts` is still reported when `"persistencia"`
    is present, for continuity, but it no longer drives the verdict.
    """
    clase_obs = np.asarray(clase_obs).reshape(-1)
    mask = np.asarray(mask, dtype=bool)
    y_true = clase_obs[mask]
    n_subset = int(mask.sum())

    filas: list[dict[str, Any]] = []
    for nombre, y_pred in predicciones.items():
        y_pred_arr = np.asarray(y_pred).reshape(-1)
        if y_pred_arr.shape[0] != n_subset:
            raise ValueError(
                f"predicciones[{nombre!r}] has {y_pred_arr.shape[0]} entries but mask selects "
                f"{n_subset} bags; they must match."
            )
        macro_f1 = float(f1_score(y_true, y_pred_arr, average="macro"))
        filas.append({"arm": nombre, "macro_f1": macro_f1, "n": n_subset})

    resultado = pd.DataFrame(filas, columns=["arm", "macro_f1", "n"])
    resultado.attrs["barra_a1_pts"] = BARRA_ACEPTACION_A1_PUNTOS

    otros_arms = [nombre for nombre in predicciones if nombre != "modelo"]
    if "modelo" not in predicciones or not otros_arms:
        resultado.attrs["a1_evaluable"] = False
        return resultado

    f1_modelo = float(resultado.loc[resultado["arm"] == "modelo", "macro_f1"].iloc[0])

    if "persistencia" in predicciones:
        f1_persistencia = float(
            resultado.loc[resultado["arm"] == "persistencia", "macro_f1"].iloc[0]
        )
        resultado.attrs["delta_modelo_vs_persistencia_pts"] = (
            f1_modelo - f1_persistencia
        ) * 100.0

    baselines = resultado.loc[resultado["arm"] != "modelo", ["arm", "macro_f1"]]
    fila_mejor_baseline = baselines.loc[baselines["macro_f1"].idxmax()]
    arm_mejor_baseline = str(fila_mejor_baseline["arm"])
    f1_mejor_baseline = float(fila_mejor_baseline["macro_f1"])
    delta_pts = (f1_modelo - f1_mejor_baseline) * 100.0
    cumplida = bool(delta_pts >= BARRA_ACEPTACION_A1_PUNTOS)

    resultado.attrs["a1_evaluable"] = True
    resultado.attrs["arm_mejor_baseline"] = arm_mejor_baseline
    resultado.attrs["f1_mejor_baseline"] = f1_mejor_baseline
    resultado.attrs["delta_modelo_vs_mejor_baseline_pts"] = delta_pts
    resultado.attrs["a1_cumplida"] = cumplida
    resultado.attrs["veredicto"] = (
        (
            "Resultado positivo: el modelo supera la barra pre-registrada de "
            f"+{BARRA_ACEPTACION_A1_PUNTOS} puntos de macro-F1 sobre la mejor linea base "
            f"(`{arm_mejor_baseline}`, macro-F1 {f1_mejor_baseline:.4f}) en el subconjunto de "
            f"variacion intra-vano (delta observado: {delta_pts:.2f} puntos)."
        )
        if cumplida
        else (
            "RESULTADO NEGATIVO reportado: el modelo no supera la barra pre-registrada de "
            f"+{BARRA_ACEPTACION_A1_PUNTOS} puntos de macro-F1 sobre la mejor linea base "
            f"(`{arm_mejor_baseline}`, macro-F1 {f1_mejor_baseline:.4f}) en el subconjunto de "
            f"variacion intra-vano (delta observado: {delta_pts:.2f} puntos). "
            "Esta es una caracterizacion descriptiva; no se itera sobre los terminos de la "
            "perdida para perseguir la barra despues de observar el resultado."
        )
    )
    return resultado


def desglose_por_circuito(
    clase_obs: np.ndarray,
    predicciones: Mapping[str, np.ndarray],
    mask: np.ndarray,
    circuito: Sequence[Any],
) -> pd.DataFrame:
    """Per-circuit macro-F1 breakdown, one row per circuit present in
    `mask`'s subset -- a REPORTING requirement, never an acceptance floor
    (spec `mil-validation-protocol`, "Per-circuit breakdown reporting"):
    it accompanies the headline result regardless of `evaluar_arms`'s A1
    outcome.
    """
    clase_obs = np.asarray(clase_obs).reshape(-1)
    mask = np.asarray(mask, dtype=bool)
    circuito_arr = np.asarray(circuito).reshape(-1)
    if circuito_arr.shape[0] != clase_obs.shape[0]:
        raise ValueError("circuito must have one entry per bag in clase_obs.")

    y_true = clase_obs[mask]
    circuitos_subset = circuito_arr[mask]

    predicciones_arr = {
        nombre: np.asarray(y_pred).reshape(-1) for nombre, y_pred in predicciones.items()
    }

    filas: list[dict[str, Any]] = []
    for nombre_circuito in sorted(set(circuitos_subset.tolist())):
        circuito_mask = circuitos_subset == nombre_circuito
        n = int(circuito_mask.sum())
        fila: dict[str, Any] = {"circuito": nombre_circuito, "n": n}
        for nombre_arm, y_pred_arr in predicciones_arr.items():
            if n >= 1:
                try:
                    macro_f1 = float(
                        f1_score(y_true[circuito_mask], y_pred_arr[circuito_mask], average="macro")
                    )
                except ValueError:
                    macro_f1 = float("nan")
            else:
                macro_f1 = float("nan")
            fila[f"macro_f1_{nombre_arm}"] = macro_f1
        filas.append(fila)

    resultado = pd.DataFrame(filas)
    resultado.attrs["nota"] = (
        "Reporting only -- nunca un piso de aceptacion. La unidad de decision es el agregado "
        "global de evaluar_arms; este desglose por circuito informa, no condiciona."
    )
    return resultado


# ---------------------------------------------------------------------------
# A3 (univariate-proxy guard) + A4 (gate-collapse detection) wiring
# ---------------------------------------------------------------------------


def guardia_proxy_univariante_mil(
    clase_observada: np.ndarray,
    X_bag: np.ndarray,
    features: Sequence[str],
    *,
    seed: int = 42,
    ari_threshold: float = 0.8,
) -> pd.DataFrame:
    """A3: wires `guardia_proxy_univariante` (reused UNCHANGED) with the
    observed 01.4 class as labels, bag-level feature means as `X`, and
    `k=4` fixed (the 4 criticality tiers) -- never left to the caller.
    """
    return guardia_proxy_univariante(
        cluster_labels=np.asarray(clase_observada),
        X=X_bag,
        features=features,
        k=4,
        seed=seed,
        ari_threshold=ari_threshold,
    )


def grafo_por_grupo_si_no_colapsado(
    gate_means: np.ndarray,
    edge_index: Any,
    labels: np.ndarray,
    n_features: int,
    *,
    near_constant_std_threshold: float = 1e-6,
) -> dict[str, Any]:
    """A4: `estadistico_colapso` (reused UNCHANGED) runs first; a collapsed
    gate matrix VOIDS the per-criticality-group reconstructed graph --
    `grafo_reconstruido_por_grupo` (also reused unchanged) is never even
    called, so a collapsed gate can never be silently interpreted as if it
    carried per-group structure.
    """
    colapso = estadistico_colapso(
        gate_means, near_constant_std_threshold=near_constant_std_threshold
    )
    if colapso["is_collapsed"]:
        return {"voided": True, "colapso": colapso, "grafos_por_grupo": None}

    grafos = grafo_reconstruido_por_grupo(gate_means, edge_index, labels, n_features)
    return {"voided": False, "colapso": colapso, "grafos_por_grupo": grafos}


# ---------------------------------------------------------------------------
# A6: temporal block split, secondary diagnostic only
# ---------------------------------------------------------------------------


def particion_bloque_temporal(
    bag_index: Any,
    ventanas_entrenamiento: Sequence[str],
    ventanas_prueba: Sequence[str],
) -> tuple[np.ndarray, np.ndarray]:
    """A6, secondary robustness diagnostic: bags whose `VENTANA` is in
    `ventanas_entrenamiento` -> `train_mask`; bags whose `VENTANA` is in
    `ventanas_prueba` -> `test_mask` (e.g. V1..V7 -> V8..V11). This split
    MUST NEVER reselect the headline metric (D8) -- callers report it
    side-by-side with the primary grouped-CV result, never in its place.
    """
    ventanas = bag_index.keys["VENTANA"].to_numpy()
    train_mask = np.isin(ventanas, list(ventanas_entrenamiento))
    test_mask = np.isin(ventanas, list(ventanas_prueba))
    return train_mask, test_mask


def evaluar_diagnostico_temporal(
    clase_obs: np.ndarray,
    predicciones: Mapping[str, np.ndarray],
    test_mask: np.ndarray,
) -> pd.DataFrame:
    """A6: scores the SAME arms on the temporal-block test subset via
    `evaluar_arms`, tagged `attrs["es_diagnostico"] = True` -- this frame
    must never replace or reselect the grouped-CV headline result (D8); it
    is reported side by side, as a robustness diagnostic only.
    """
    resultado = evaluar_arms(clase_obs, predicciones, test_mask)
    resultado.attrs["es_diagnostico"] = True
    resultado.attrs["nota"] = (
        "Split temporal (bloque de ventanas de entrenamiento -> bloque de ventanas de "
        "prueba): diagnostico de robustez SECUNDARIO (A6). Nunca reselecciona la metrica "
        "principal de StratifiedGroupKFold; se reporta solo lado a lado."
    )
    return resultado


# ---------------------------------------------------------------------------
# D7: BagPredictor + the simulator/SHAP contract adapters
# ---------------------------------------------------------------------------


class BagPredictor:
    """Adapts a fitted `MILBagRegressor` to bag-level u-hat / class / proba,
    and to the simulator's per-row `predict_fn` contract (design D7).

    `feature_names` carries the full `p = 71 + K` instance feature list,
    including `COD_CAUSA` and its indicator block (design D4) -- kept for
    interface symmetry with `KernelShapTopVarsExtractor`, which is
    constructed with the same `features` list downstream.
    """

    def __init__(
        self,
        model: Any,
        feature_names: Sequence[str],
        geometria: Geometria,
        *,
        device: str = "cpu",
    ) -> None:
        self.model = model
        self.feature_names = list(feature_names)
        self.geometria = geometria
        self.device = device

    def _n_bags_de(self, instance_bag_arr: np.ndarray) -> int:
        return int(instance_bag_arr.max()) + 1 if instance_bag_arr.size else 0

    def predict(self, X_inst: np.ndarray, instance_bag: np.ndarray | None = None) -> np.ndarray:
        """u-hat per bag. When `instance_bag` is None, every row is its own
        singleton bag (`n_obs = 1`) -- the convention `predict_fn` uses for
        the simulator/SHAP per-row contract."""
        X_inst = np.asarray(X_inst, dtype=np.float32)
        n_rows = X_inst.shape[0]

        if instance_bag is None:
            instance_bag_arr = np.arange(n_rows, dtype=np.int64)
        else:
            instance_bag_arr = np.asarray(instance_bag, dtype=np.int64)
        n_bags = self._n_bags_de(instance_bag_arr)

        self.model.eval()
        with torch.no_grad():
            x_tensor = torch.as_tensor(X_inst, dtype=torch.float32, device=self.device)
            bag_tensor = torch.as_tensor(instance_bag_arr, dtype=torch.long, device=self.device)
            output = self.model(x_tensor, bag_tensor, n_bags)
        p_bag = output["p_bag"].detach().cpu().numpy()
        return np.expm1(p_bag)

    def predict_class(
        self,
        X_inst: np.ndarray,
        n_obs: np.ndarray,
        instance_bag: np.ndarray | None = None,
    ) -> np.ndarray:
        """Hard nearest-centroid class over `(OBSERVED n_obs, predicted
        u-hat)` -- `n_obs` is always caller-supplied and observed, never
        predicted (design boundary, D8 headline note)."""
        u = self.predict(X_inst, instance_bag=instance_bag)
        n_obs_arr = np.asarray(n_obs, dtype=np.float64)
        clase, _ = asignar_clase(n_obs_arr, u, self.geometria)
        return clase

    def predict_proba(
        self, X_inst: np.ndarray, instance_bag: np.ndarray | None = None
    ) -> np.ndarray:
        """`(n_bags, 2)`: `[1 - P(Alto), P(Alto)]`. `KernelShapTopVarsExtractor`
        hardcodes `predict_proba_positiva`, which reads column 1 whenever the
        output has more than one column (`circuit_analysis.py:96-99`) -- a
        4-class matrix would silently explain the Medio tier, so this always
        returns exactly 2 columns (D7)."""
        u = self.predict(X_inst, instance_bag=instance_bag)
        if instance_bag is None:
            n_obs = np.ones(u.shape[0], dtype=np.float64)
        else:
            instance_bag_arr = np.asarray(instance_bag, dtype=np.int64)
            n_bags = self._n_bags_de(instance_bag_arr)
            n_obs = np.bincount(instance_bag_arr, minlength=n_bags).astype(np.float64)

        distribucion = distribucion_suave(n_obs, u, self.geometria)  # (n_bags, 4)
        p_alto = distribucion[:, 3]
        return np.stack([1.0 - p_alto, p_alto], axis=1)


def predict_fn(
    model: BagPredictor,
    X: np.ndarray,
    *,
    device: str = "cpu",
    batch_size: int = 1024,
) -> dict[str, Any]:
    """Simulator contract (`chec_local_interpreter/simulator.py:182-193`):
    `{"fused_probs": (n, 4), "predicted_classes": (n,)}`. One row == one
    single-instance bag with `n_obs = 1` (D7). The simulator itself stays
    out of scope here -- this only pins the shape contract so a later
    simulator can consume `model` (a `BagPredictor`) unchanged.
    """
    del device, batch_size  # accepted for contract compatibility; predict() is not batched here
    X = np.asarray(X, dtype=np.float32)
    n_obs = np.ones(X.shape[0], dtype=np.float64)

    u = model.predict(X, instance_bag=None)
    fused_probs = distribucion_suave(n_obs, u, model.geometria)  # (n, 4)
    predicted_classes, _ = asignar_clase(n_obs, u, model.geometria)
    return {"fused_probs": fused_probs, "predicted_classes": predicted_classes}


# ---------------------------------------------------------------------------
# Kernel SHAP -> Borda ranking (D7)
# ---------------------------------------------------------------------------

# Variables that are exposure/severity BY CONSTRUCTION: a high relevance on
# them describes how much load sits behind the vano, not an actionable cause.
# CNT_VN is deliberately excluded (D6, spec `criticality-assignment-from-014`):
# it answers to COD_EQ_PROTEGE, not to exposure.
COLUMNAS_EXPOSICION_SEVERIDAD: tuple[str, ...] = ("CAPACIDAD_NOMINAL", "PROMEDIO_KWH_TRF")
NOTA_EXPOSICION_SEVERIDAD = "exposicion/severidad por construccion, no causa accionable"

_COLUMNAS_RANKING_BORDA = ("_var", "_borda", "nota_exposicion_severidad")


def nota_exposicion_severidad(nombre_variable: str) -> str:
    """Empty string for actionable variables, the standing caveat otherwise."""
    return NOTA_EXPOSICION_SEVERIDAD if nombre_variable in COLUMNAS_EXPOSICION_SEVERIDAD else ""


def construir_ranking_borda(
    keys: pd.DataFrame,
    indices_muestra: Sequence[int] | np.ndarray,
    top_vars_por_bolsa: Sequence[Mapping[str, float]],
    *,
    group_cols: Sequence[str] = ("CIRCUITO", "FID_VANO", "VENTANA"),
    top_k: int = 20,
) -> pd.DataFrame:
    """Borda ranking in LONG format, one row per (group, variable).

    `top_vars_por_bolsa` is what `KernelShapTopVarsExtractor.calcular_top_vars`
    returns: a SEQUENCE aligned positionally with `indices_muestra`, never a
    mapping keyed by bag index. The length guard below turns that confusion
    into an immediate error instead of an `AttributeError` deep in a
    comprehension.

    Long format is deliberate. `agregar_borda` collapses each group into a
    single `RELEVANCIA_VARS` dict with no `_var` column, which leaves nowhere
    to hang a per-variable annotation -- the exact reason the exposure/severity
    note used to come out empty.
    """
    indices_muestra = np.asarray(indices_muestra, dtype=int)
    top_vars_por_bolsa = list(top_vars_por_bolsa)
    if len(top_vars_por_bolsa) != len(indices_muestra):
        raise ValueError(
            "top_vars_por_bolsa debe ser una secuencia alineada posicionalmente con "
            f"indices_muestra: {len(top_vars_por_bolsa)} relevancias para "
            f"{len(indices_muestra)} bolsas."
        )

    group_cols = list(group_cols)
    faltantes = [c for c in group_cols if c not in keys.columns]
    if faltantes:
        raise ValueError(f"keys no tiene las columnas de agrupacion {faltantes}.")

    marco = pd.DataFrame({c: keys[c].to_numpy()[indices_muestra] for c in group_cols})
    marco["_TOP_VARS"] = top_vars_por_bolsa

    borda = agregar_borda(marco, group_cols=group_cols, top_k=top_k)
    if borda.empty or "RELEVANCIA_VARS" not in borda.columns:
        return pd.DataFrame(columns=group_cols + list(_COLUMNAS_RANKING_BORDA))

    filas = []
    for registro in borda.to_dict("records"):
        relevancias = registro.get("RELEVANCIA_VARS") or {}
        grupo = {c: registro[c] for c in group_cols}
        for var, puntaje in relevancias.items():
            filas.append(
                {
                    **grupo,
                    "_var": var,
                    "_borda": float(puntaje),
                    "nota_exposicion_severidad": nota_exposicion_severidad(var),
                }
            )

    if not filas:
        return pd.DataFrame(columns=group_cols + list(_COLUMNAS_RANKING_BORDA))

    ranking = pd.DataFrame(filas)
    return ranking.sort_values(
        group_cols + ["_borda"],
        ascending=[True] * len(group_cols) + [False],
        kind="stable",
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Per-class breakdown (confusion matrix + per-class F1)
# ---------------------------------------------------------------------------

N_CLASES_CRITICIDAD = 4


def desglose_por_clase(
    clase_obs: np.ndarray,
    predicciones: Mapping[str, np.ndarray],
    mask: np.ndarray,
) -> dict[str, dict[str, Any]]:
    """Confusion matrix + per-class precision/recall/F1 + accuracy, per arm.

    macro-F1 cannot distinguish "uniformly mediocre" from "abandoned one
    class", and on this dataset that IS the question: `Alto` is 10.21% of
    the within-vano-variation subset, an arm that predicts the other three
    perfectly and never predicts `Alto` scores 0.75 macro-F1 and 89.8%
    accuracy, and the observed model scores 0.7704.

    `accuracy` is reported but is never the headline -- the majority
    baseline already scores 0.4384 accuracy against 0.1524 macro-F1.
    `clases_abandonadas` names the tiers an arm never predicts at all, which
    is the single fact the scalar metrics hide.

    The matrix is ALWAYS `(4, 4)` with rows = observed and columns =
    predicted, even when an arm never emits some tier -- a matrix whose
    shape depends on the predictions cannot be compared across arms.
    """
    clase_obs = np.asarray(clase_obs).reshape(-1)
    mask = np.asarray(mask, dtype=bool)
    y_true = clase_obs[mask]
    n_subset = int(mask.sum())
    etiquetas = list(range(N_CLASES_CRITICIDAD))

    salida: dict[str, dict[str, Any]] = {}
    for nombre, y_pred in predicciones.items():
        y_pred = np.asarray(y_pred).reshape(-1)
        if y_pred.shape[0] != n_subset:
            raise ValueError(
                f"predicciones[{nombre!r}] tiene {y_pred.shape[0]} entradas pero la mask "
                f"selecciona {n_subset} bolsas; la longitud debe coincidir."
            )

        matriz = confusion_matrix(y_true, y_pred, labels=etiquetas)
        precision, recall, f1, soporte = precision_recall_fscore_support(
            y_true, y_pred, labels=etiquetas, zero_division=0
        )
        predichas = set(np.unique(y_pred).tolist())

        salida[nombre] = {
            "n": n_subset,
            "accuracy": float(np.mean(y_true == y_pred)),
            "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=etiquetas)),
            "matriz_confusion": matriz,
            "por_clase": [
                {
                    "clase": k,
                    "grupo": GRUPOS[k],
                    "precision": float(precision[k]),
                    "recall": float(recall[k]),
                    "f1": float(f1[k]),
                    "soporte": int(soporte[k]),
                }
                for k in etiquetas
            ],
            "clases_abandonadas": [k for k in etiquetas if k not in predichas],
        }
    return salida


def formatear_desglose_por_clase(desglose: Mapping[str, Mapping[str, Any]]) -> str:
    """Render `desglose_por_clase` for a notebook cell."""
    lineas: list[str] = []
    for nombre, d in desglose.items():
        lineas.append(
            f"=== {nombre} === n={d['n']:,}  accuracy={d['accuracy']:.4f}  "
            f"macro-F1={d['macro_f1']:.4f}"
        )
        lineas.append("  matriz de confusion (fila = OBSERVADA, columna = PREDICHA)")
        encabezado = "      " + "".join(f"{GRUPOS[k]:>12}" for k in range(N_CLASES_CRITICIDAD))
        lineas.append(encabezado)
        for k, fila in enumerate(d["matriz_confusion"]):
            lineas.append(f"  {GRUPOS[k]:<10}" + "".join(f"{int(v):>12,}" for v in fila))
        lineas.append(f"  {'grupo':<12}{'prec':>8}{'recall':>8}{'F1':>8}{'soporte':>10}")
        for f in d["por_clase"]:
            lineas.append(
                f"  {f['grupo']:<12}{f['precision']:>8.4f}{f['recall']:>8.4f}"
                f"{f['f1']:>8.4f}{f['soporte']:>10,}"
            )
        if d["clases_abandonadas"]:
            nombres = ", ".join(GRUPOS[k] for k in d["clases_abandonadas"])
            lineas.append(f"  AVISO: nunca predice {nombres} -- macro-F1 solo no lo mostraria.")
        lineas.append("")
    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Viewer helpers (notebook 10 runs read-only by default)
# ---------------------------------------------------------------------------


def matriz_confusion_porcentaje(matriz: np.ndarray) -> np.ndarray:
    """Row-normalised confusion matrix, in percent.

    Normalised by OBSERVED row, so each row reads "of the bags that WERE
    tier k, where did they end up?" -- the recall view. That is the
    orientation in which an abandoned tier is a row of zeros on the
    diagonal, which is the failure macro-F1 hides. A tier with no observed
    bags yields zeros, never NaN: one empty row must not poison the table.
    """
    matriz = np.asarray(matriz, dtype=np.float64)
    totales = matriz.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = np.where(totales > 0, matriz / np.where(totales > 0, totales, 1.0) * 100.0, 0.0)
    return pct


def tabla_variables(
    features: Sequence[str],
    modalidades: Mapping[str, Sequence[int]],
    adjacency: np.ndarray,
) -> pd.DataFrame:
    """One row per input variable: modality and its role in the fixed graph.

    `grado_entrada` is what the propagation step can CHANGE about a variable
    (`index_add` only writes at `edge_cols`), so a variable with in-degree 0
    -- every degree-0 `COD_CAUSA_*` indicator -- is passed through the graph
    untouched by construction. `aristas_cruzadas` counts the edges that join
    the two modalities, the model's only graph-borne cross-modality path.
    """
    features = list(features)
    adjacency = np.asarray(adjacency, dtype=np.float64)
    if adjacency.shape != (len(features), len(features)):
        raise ValueError(
            f"la adyacencia es {adjacency.shape} pero hay {len(features)} features; "
            "deben coincidir."
        )

    modalidad_de = {}
    for nombre, indices in modalidades.items():
        for i in indices:
            modalidad_de[int(i)] = nombre

    filas_idx, cols_idx = np.nonzero(adjacency)
    grado_salida = np.zeros(len(features), dtype=int)
    grado_entrada = np.zeros(len(features), dtype=int)
    cruzadas = np.zeros(len(features), dtype=int)
    for r, c in zip(filas_idx, cols_idx):
        grado_salida[r] += 1
        grado_entrada[c] += 1
        if modalidad_de.get(int(r)) != modalidad_de.get(int(c)):
            cruzadas[r] += 1
            cruzadas[c] += 1

    return pd.DataFrame(
        {
            "variable": features,
            "modalidad": [modalidad_de.get(i, "?") for i in range(len(features))],
            "grado_entrada": grado_entrada,
            "grado_salida": grado_salida,
            "aristas_cruzadas": cruzadas,
            "en_grafo": (grado_entrada + grado_salida) > 0,
        }
    )
