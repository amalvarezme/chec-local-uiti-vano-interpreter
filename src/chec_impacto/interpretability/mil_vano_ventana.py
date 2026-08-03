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
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedGroupKFold

from chec_impacto.interpretability.mgcecdl_graph import (
    estadistico_colapso,
    grafo_reconstruido_por_grupo,
    guardia_proxy_univariante,
)
from chec_impacto.models.criticality_assignment import Geometria, asignar_clase, distribucion_suave

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

    modelo = RandomForestRegressor(n_estimators=200, random_state=seed)
    modelo.fit(X_train, np.log1p(y_train))
    log_u_pred = modelo.predict(X_test)
    u_pred = np.expm1(log_u_pred)

    n_obs_test = np.asarray(n_obs_test, dtype=np.float64)
    clase_pred, _ = asignar_clase(n_obs_test, u_pred, geometria)
    return clase_pred


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
    subset. When both `"modelo"` and `"persistencia"` are present, attaches
    the A1 pass/fail verdict against `BARRA_ACEPTACION_A1_PUNTOS` as
    `frame.attrs` -- a missed bar is reported as a descriptive
    characterization plus an explicit negative result, never as a trigger to
    keep iterating loss terms in search of the bar (spec
    `mil-validation-protocol`, "Pre-registered +5-point acceptance bar").
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

    if "modelo" not in predicciones or "persistencia" not in predicciones:
        resultado.attrs["a1_evaluable"] = False
        return resultado

    f1_modelo = float(resultado.loc[resultado["arm"] == "modelo", "macro_f1"].iloc[0])
    f1_persistencia = float(resultado.loc[resultado["arm"] == "persistencia", "macro_f1"].iloc[0])
    delta_pts = (f1_modelo - f1_persistencia) * 100.0
    cumplida = bool(delta_pts >= BARRA_ACEPTACION_A1_PUNTOS)

    resultado.attrs["a1_evaluable"] = True
    resultado.attrs["delta_modelo_vs_persistencia_pts"] = delta_pts
    resultado.attrs["a1_cumplida"] = cumplida
    resultado.attrs["veredicto"] = (
        (
            "Resultado positivo: el modelo supera la barra pre-registrada de "
            f"+{BARRA_ACEPTACION_A1_PUNTOS} puntos de macro-F1 sobre persistencia en el "
            f"subconjunto de variacion intra-vano (delta observado: {delta_pts:.2f} puntos)."
        )
        if cumplida
        else (
            "RESULTADO NEGATIVO reportado: el modelo no supera la barra pre-registrada de "
            f"+{BARRA_ACEPTACION_A1_PUNTOS} puntos de macro-F1 sobre persistencia en el "
            f"subconjunto de variacion intra-vano (delta observado: {delta_pts:.2f} puntos). "
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
