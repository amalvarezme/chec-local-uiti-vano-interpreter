"""RED/GREEN tests for the MIL validation harness
(`src/chec_impacto/interpretability/mil_vano_ventana.py`).

Covers the frozen within-vano-variation subset, grouped-CV fold assignment,
the three mandatory baselines, `evaluar_arms`'s A1 pass/fail branches, the
per-circuit reporting breakdown, the A3/A4 guard wiring, the temporal-block
diagnostic (A6), and `BagPredictor`/`predict_fn`'s simulator/SHAP contract.
See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain
    `mil-validation-protocol`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D7, D8)
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import f1_score as sklearn_f1_score

from chec_impacto.data.bags import BagIndex
from chec_impacto.models.criticality_assignment import Geometria, distribucion_suave
from chec_impacto.models.mgcecdl import MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import construir_edge_index
from chec_impacto.models.mgcecdl_mil import MILBagRegressor
from chec_impacto.interpretability.mil_vano_ventana import (
    BARRA_ACEPTACION_A1_PUNTOS,
    BagPredictor,
    agrupar_por_claves,
    baseline_estructural,
    baseline_mayoritaria,
    baseline_persistencia,
    construir_folds_agrupados,
    desglose_por_circuito,
    evaluar_arms,
    evaluar_diagnostico_temporal,
    grafo_por_grupo_si_no_colapsado,
    guardia_proxy_univariante_mil,
    particion_bloque_temporal,
    predict_fn,
    subconjunto_variacion_intravano,
)

MODULE_PATH = Path("src/chec_impacto/interpretability/mil_vano_ventana.py")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _geometria_fixture() -> Geometria:
    return Geometria(
        logs=(False, True),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array(
            [
                [0.0, -2.0],  # Bajo
                [0.0, -0.5],  # Medio
                [0.0, 0.5],  # Medio-Alto
                [0.0, 2.0],  # Alto
            ]
        ),
    )


def _bag_index_variacion() -> tuple[BagIndex, np.ndarray]:
    """6 bags: vano V0 (3 windows, varying class), vano V1 (1 window,
    excluded regardless of class), vano V2 (2 windows, constant class)."""
    keys = pd.DataFrame(
        {
            "CIRCUITO": ["C0", "C0", "C0", "C0", "C1", "C1"],
            "FID_VANO": ["V0", "V0", "V0", "V1", "V2", "V2"],
            "VENTANA": ["W1", "W2", "W3", "W1", "W1", "W2"],
        }
    )
    n_bags = 6
    counts = np.ones(n_bags, dtype=np.int64)
    offsets = np.arange(n_bags + 1, dtype=np.int64)
    instance_bag = np.arange(n_bags, dtype=np.int64)
    group = np.array(["C0|V0", "C0|V0", "C0|V0", "C0|V1", "C1|V2", "C1|V2"], dtype=object)
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    bag_index = BagIndex(
        keys=keys,
        instance_bag=instance_bag,
        offsets=offsets,
        counts=counts,
        y=y,
        group=group,
        instance_rows=np.arange(n_bags, dtype=np.int64),
    )
    clase_observada = np.array([0, 1, 0, 2, 3, 3], dtype=np.int64)
    return bag_index, clase_observada


def _bag_index_para_folds() -> tuple[BagIndex, np.ndarray]:
    especificacion = [
        ("V0", 3), ("V1", 1), ("V2", 2), ("V3", 4), ("V4", 1),
        ("V5", 2), ("V6", 3), ("V7", 1), ("V8", 2),
    ]
    circuitos = ["C0", "C0", "C1", "C1", "C0", "C1", "C0", "C1", "C0"]
    clases_ciclo = [0, 1, 2, 3]

    filas_circuito: list[str] = []
    filas_vano: list[str] = []
    filas_ventana: list[str] = []
    filas_clase: list[int] = []
    filas_grupo: list[str] = []
    for idx, ((vano, n_windows), circuito) in enumerate(zip(especificacion, circuitos)):
        clase = clases_ciclo[idx % 4]
        for w in range(n_windows):
            filas_circuito.append(circuito)
            filas_vano.append(vano)
            filas_ventana.append(f"W{w + 1}")
            filas_clase.append(clase)
            filas_grupo.append(f"{circuito}|{vano}")

    n_bags = len(filas_circuito)
    counts = np.ones(n_bags, dtype=np.int64)
    offsets = np.arange(n_bags + 1, dtype=np.int64)
    instance_bag = np.arange(n_bags, dtype=np.int64)
    keys = pd.DataFrame(
        {"CIRCUITO": filas_circuito, "FID_VANO": filas_vano, "VENTANA": filas_ventana}
    )
    group = np.array(filas_grupo, dtype=object)
    y = np.linspace(1.0, 2.0, n_bags)
    clase_observada = np.array(filas_clase, dtype=np.int64)
    bag_index = BagIndex(
        keys=keys,
        instance_bag=instance_bag,
        offsets=offsets,
        counts=counts,
        y=y,
        group=group,
        instance_rows=np.arange(n_bags, dtype=np.int64),
    )
    return bag_index, clase_observada


_FEATURES = ["a", "b", "c", "d", "e", "ind"]
_EDGES = [
    {"source": "a", "target": "b", "weight": 0.5},
    {"source": "b", "target": "c", "weight": 0.8},
    {"source": "c", "target": "d", "weight": 0.3},
    {"source": "d", "target": "e", "weight": 0.6},
]
_MODALITY_FEATURE_INDICES = {"climaticos": [0, 1, 2], "estructurales": [3, 4, 5]}


def _tiny_adjacency() -> np.ndarray:
    positions = {name: index for index, name in enumerate(_FEATURES)}
    matrix = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for edge in _EDGES:
        matrix[positions[edge["source"]], positions[edge["target"]]] = edge["weight"]
    return matrix


def _tiny_edge_index():
    return construir_edge_index(_tiny_adjacency(), _FEATURES, _EDGES)


def _tiny_bag_predictor() -> BagPredictor:
    base = MGCECDLRegressor(
        modality_feature_indices=_MODALITY_FEATURE_INDICES,
        hidden_dim=16,
        embed_dim=4,
        dropout=0.0,
        temperature=1.0,
    )
    model = MILBagRegressor(
        base=base,
        adjacency=_tiny_adjacency(),
        edge_index=_tiny_edge_index(),
        alpha=0.3,
        attn_dim=8,
    )
    model.eval()
    return BagPredictor(model=model, feature_names=_FEATURES, geometria=_geometria_fixture())


# ---------------------------------------------------------------------------
# 4.1 / 4.2 -- subconjunto_variacion_intravano
# ---------------------------------------------------------------------------


def test_subconjunto_variacion_intravano_marks_multi_window_varying_vanos() -> None:
    bag_index, clase_observada = _bag_index_variacion()
    mask = subconjunto_variacion_intravano(bag_index, clase_observada)
    np.testing.assert_array_equal(mask, [True, True, True, False, False, False])


def test_subconjunto_variacion_intravano_is_frozen_pure_and_idempotent() -> None:
    """Calling the mask builder twice on the same observed inputs must give
    the identical result -- it depends on nothing fold-related."""
    bag_index, clase_observada = _bag_index_variacion()
    mask_a = subconjunto_variacion_intravano(bag_index, clase_observada)
    mask_b = subconjunto_variacion_intravano(bag_index, clase_observada)
    np.testing.assert_array_equal(mask_a, mask_b)


# ---------------------------------------------------------------------------
# 4.3 / 4.4 -- grouped CV fold assignment + agrupar_por_claves
# ---------------------------------------------------------------------------


def test_construir_folds_agrupados_no_vano_crosses_fold_boundary() -> None:
    bag_index, clase_observada = _bag_index_para_folds()
    folds = construir_folds_agrupados(bag_index, clase_observada, n_splits=3, seed=42)

    assert len(folds) == 3
    fold_por_bag = np.full(len(clase_observada), -1, dtype=int)
    for fold_id, (_, test_idx) in enumerate(folds):
        fold_por_bag[test_idx] = fold_id
    assert np.all(fold_por_bag >= 0), "every bag must be in exactly one fold's test set"

    grupo_a_folds: dict[str, set[int]] = {}
    for bag_pos, grupo in enumerate(bag_index.group):
        grupo_a_folds.setdefault(grupo, set()).add(int(fold_por_bag[bag_pos]))
    for grupo, folds_vistos in grupo_a_folds.items():
        assert len(folds_vistos) == 1, f"vano {grupo} spans folds {folds_vistos}"


def test_agrupar_por_claves_generic_groupby_mean() -> None:
    values = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]])
    keys = pd.DataFrame({"CIRCUITO": ["C0", "C0", "C1", "C1"], "FID_VANO": ["V0", "V0", "V1", "V1"]})
    pooled, key_index = agrupar_por_claves(values, keys)

    assert pooled.shape == (2, 2)
    np.testing.assert_allclose(pooled[0], [2.0, 3.0])
    np.testing.assert_allclose(pooled[1], [6.0, 7.0])
    assert list(key_index.columns) == ["CIRCUITO", "FID_VANO"]


# ---------------------------------------------------------------------------
# 4.5 / 4.8 -- baseline_mayoritaria
# ---------------------------------------------------------------------------


def test_baseline_mayoritaria_returns_training_folds_modal_class() -> None:
    clase_train = np.array([1, 1, 2, 3, 1])
    prediccion = baseline_mayoritaria(clase_train, n_test=4)
    assert prediccion.shape == (4,)
    assert np.all(prediccion == 1)


# ---------------------------------------------------------------------------
# 4.6 / 4.8 -- baseline_estructural
# ---------------------------------------------------------------------------


def test_baseline_estructural_predicts_valid_classes_and_never_calls_linea_base_sin_grafo() -> None:
    rng = np.random.default_rng(3)
    X_train = rng.normal(size=(10, 3))
    y_train = rng.uniform(0.5, 50.0, size=10)
    X_test = rng.normal(size=(4, 3))
    n_obs_test = np.array([1.0, 2.0, 1.0, 3.0])
    geometria = _geometria_fixture()

    pred_a = baseline_estructural(X_train, y_train, X_test, n_obs_test, geometria, seed=7)
    pred_b = baseline_estructural(X_train, y_train, X_test, n_obs_test, geometria, seed=7)

    assert pred_a.shape == (4,)
    assert np.array_equal(pred_a, pred_b), "same seed must reproduce identical predictions"
    assert set(pred_a.tolist()) <= {0, 1, 2, 3}


def test_baseline_estructural_never_calls_or_imports_linea_base_sin_grafo() -> None:
    """`linea_base_sin_grafo` emits KMeans cluster ids, not criticality
    classes, and pools via a hardcoded groupby with no window key -- design
    D8 explicitly forbids reusing it here. The name may still appear in
    prose (explaining WHY it is not reused), so this guards against an
    actual import or call, not against the docstring mentioning it."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "import linea_base_sin_grafo" not in source
    assert "linea_base_sin_grafo(" not in source


# ---------------------------------------------------------------------------
# 4.7 / 4.8 -- baseline_persistencia
# ---------------------------------------------------------------------------


def test_baseline_persistencia_uses_other_windows_modal_class_and_excludes_singletons() -> None:
    bag_index, clase_observada = _bag_index_variacion()
    test_mask = np.ones(6, dtype=bool)

    predicciones, tiene_prediccion = baseline_persistencia(bag_index, clase_observada, test_mask)

    # V0 (bags 0,1,2; classes 0,1,0): each bag's "other" classes have a tie broken
    # toward the smaller class value by pandas' Series.mode() (ascending sort).
    assert predicciones[0] == 0  # others = [1, 0] -> tie -> 0
    assert predicciones[1] == 0  # others = [0, 0] -> 0
    assert predicciones[2] == 0  # others = [0, 1] -> tie -> 0
    assert tiene_prediccion[0] and tiene_prediccion[1] and tiene_prediccion[2]

    # V1 (bag 3): singleton vano within test_mask -> no other bag -> no prediction.
    assert not tiene_prediccion[3]

    # V2 (bags 4,5; classes 3,3): each bag's only "other" bag is the other -> 3.
    assert predicciones[4] == 3
    assert predicciones[5] == 3
    assert tiene_prediccion[4] and tiene_prediccion[5]


# ---------------------------------------------------------------------------
# 4.9 / 4.10 -- evaluar_arms: A1 bar pass/fail, negative-result reporting
# ---------------------------------------------------------------------------


def test_a1_bar_is_a_module_constant_never_a_caller_parameter() -> None:
    firma = inspect.signature(evaluar_arms)
    assert "barra" not in firma.parameters
    assert "bar" not in firma.parameters
    assert BARRA_ACEPTACION_A1_PUNTOS == 5.0


def test_evaluar_arms_reports_all_arms_and_a1_pass_path() -> None:
    """Model beats every baseline (including the strongest, `persistencia`)
    by more than the bar -> A1 passes, and the verdict names the runner-up
    baseline it had to clear (spec change: A1 must clear the BEST baseline,
    not persistence alone)."""
    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    mask = np.ones(8, dtype=bool)

    modelo_perfecto = y_true.copy()
    persistencia_mediocre = np.array([0, 1, 1, 0, 2, 3, 3, 2])

    predicciones = {
        "modelo": modelo_perfecto,
        "persistencia": persistencia_mediocre,
        "mayoritaria": np.zeros(8, dtype=int),
        "estructural": np.array([1, 1, 1, 1, 2, 2, 2, 2]),
    }
    resultado = evaluar_arms(y_true, predicciones, mask)

    assert set(resultado["arm"]) == set(predicciones.keys())

    f1_modelo_esperado = sklearn_f1_score(y_true, modelo_perfecto, average="macro")
    f1_persistencia_esperada = sklearn_f1_score(y_true, persistencia_mediocre, average="macro")
    delta_persistencia_esperado_pts = (f1_modelo_esperado - f1_persistencia_esperada) * 100.0
    assert delta_persistencia_esperado_pts >= BARRA_ACEPTACION_A1_PUNTOS, (
        "fixture must be built to pass A1"
    )

    # `persistencia` is the strongest non-model arm in this fixture -> it is
    # the best baseline, and the verdict delta equals the persistence delta.
    np.testing.assert_allclose(
        resultado.loc[resultado["arm"] == "modelo", "macro_f1"].iloc[0], f1_modelo_esperado
    )
    assert resultado.attrs["barra_a1_pts"] == BARRA_ACEPTACION_A1_PUNTOS
    assert resultado.attrs["delta_modelo_vs_persistencia_pts"] == pytest.approx(
        delta_persistencia_esperado_pts
    )
    assert resultado.attrs["arm_mejor_baseline"] == "persistencia"
    assert resultado.attrs["f1_mejor_baseline"] == pytest.approx(f1_persistencia_esperada)
    assert resultado.attrs["delta_modelo_vs_mejor_baseline_pts"] == pytest.approx(
        delta_persistencia_esperado_pts
    )
    assert resultado.attrs["a1_cumplida"] is True
    assert "positivo" in resultado.attrs["veredicto"].lower()
    assert "persistencia" in resultado.attrs["veredicto"]


def test_evaluar_arms_a1_bar_missed_triggers_negative_result_path() -> None:
    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    mask = np.ones(8, dtype=bool)
    persistencia_mediocre = np.array([0, 1, 1, 0, 2, 3, 3, 2])

    predicciones = {
        "modelo": persistencia_mediocre.copy(),  # identical to persistence -> delta == 0
        "persistencia": persistencia_mediocre,
        "mayoritaria": np.zeros(8, dtype=int),
    }
    resultado = evaluar_arms(y_true, predicciones, mask)

    assert resultado.attrs["a1_cumplida"] is False
    assert resultado.attrs["delta_modelo_vs_persistencia_pts"] == pytest.approx(0.0)
    assert resultado.attrs["arm_mejor_baseline"] == "persistencia"
    assert resultado.attrs["delta_modelo_vs_mejor_baseline_pts"] == pytest.approx(0.0)
    veredicto = resultado.attrs["veredicto"].lower()
    assert "negativo" in veredicto
    assert "no se itera" in veredicto


def test_evaluar_arms_a1_gate_uses_best_baseline_not_just_persistence() -> None:
    """The exact hole this change closes: model clears persistence by a wide
    margin but a structural (no-climate) arm beats the model outright -> A1
    must FAIL and name `estructural` as the baseline it lost to."""
    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    mask = np.ones(8, dtype=bool)

    modelo = np.array([0, 0, 1, 1, 2, 3, 3, 3])
    persistencia = np.array([0, 1, 1, 0, 2, 3, 3, 2])
    estructural = np.array([0, 0, 1, 1, 2, 2, 3, 3])  # perfect -> beats modelo
    mayoritaria = np.zeros(8, dtype=int)

    predicciones = {
        "modelo": modelo,
        "persistencia": persistencia,
        "estructural": estructural,
        "mayoritaria": mayoritaria,
    }
    resultado = evaluar_arms(y_true, predicciones, mask)

    f1_modelo = sklearn_f1_score(y_true, modelo, average="macro")
    f1_persistencia = sklearn_f1_score(y_true, persistencia, average="macro")
    f1_estructural = sklearn_f1_score(y_true, estructural, average="macro")
    assert (f1_modelo - f1_persistencia) * 100.0 >= BARRA_ACEPTACION_A1_PUNTOS, (
        "fixture must beat persistence comfortably"
    )
    assert f1_estructural > f1_modelo, "fixture must have the structural arm beat the model"

    assert resultado.attrs["arm_mejor_baseline"] == "estructural"
    assert resultado.attrs["f1_mejor_baseline"] == pytest.approx(f1_estructural)
    assert resultado.attrs["a1_cumplida"] is False
    delta_mejor = resultado.attrs["delta_modelo_vs_mejor_baseline_pts"]
    assert delta_mejor == pytest.approx((f1_modelo - f1_estructural) * 100.0)
    assert delta_mejor < 0

    # Continuity: the persistence-only delta is still reported, and it
    # differs from the delta that actually drives the verdict.
    delta_persistencia = resultado.attrs["delta_modelo_vs_persistencia_pts"]
    assert delta_persistencia == pytest.approx((f1_modelo - f1_persistencia) * 100.0)
    assert delta_persistencia != pytest.approx(delta_mejor)

    veredicto = resultado.attrs["veredicto"].lower()
    assert "negativo" in veredicto
    assert "estructural" in veredicto


def test_evaluar_arms_a1_bar_met_names_runner_up_baseline_in_verdict() -> None:
    """Model beats every baseline by more than the bar -> A1 passes, and the
    positive verdict names the strongest (runner-up) baseline it cleared."""
    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    mask = np.ones(8, dtype=bool)

    modelo = y_true.copy()  # perfect
    persistencia = np.array([0, 1, 1, 0, 2, 3, 3, 2])
    estructural = np.array([1, 1, 1, 1, 2, 2, 2, 2])
    mayoritaria = np.zeros(8, dtype=int)

    predicciones = {
        "modelo": modelo,
        "persistencia": persistencia,
        "estructural": estructural,
        "mayoritaria": mayoritaria,
    }
    resultado = evaluar_arms(y_true, predicciones, mask)

    f1_persistencia = sklearn_f1_score(y_true, persistencia, average="macro")
    f1_estructural = sklearn_f1_score(y_true, estructural, average="macro")
    f1_mayoritaria = sklearn_f1_score(y_true, mayoritaria, average="macro")
    mejor_esperado = max(
        ("persistencia", f1_persistencia),
        ("estructural", f1_estructural),
        ("mayoritaria", f1_mayoritaria),
        key=lambda par: par[1],
    )

    assert resultado.attrs["a1_cumplida"] is True
    assert resultado.attrs["arm_mejor_baseline"] == mejor_esperado[0]
    assert resultado.attrs["f1_mejor_baseline"] == pytest.approx(mejor_esperado[1])
    assert mejor_esperado[0] in resultado.attrs["veredicto"]


def test_evaluar_arms_evaluable_without_persistence_arm() -> None:
    """A1 no longer requires `persistencia` specifically -- `modelo` plus any
    one other arm is enough to evaluate the gate."""
    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    mask = np.ones(8, dtype=bool)

    modelo = y_true.copy()
    mayoritaria = np.zeros(8, dtype=int)

    predicciones = {"modelo": modelo, "mayoritaria": mayoritaria}
    resultado = evaluar_arms(y_true, predicciones, mask)

    f1_modelo = sklearn_f1_score(y_true, modelo, average="macro")
    f1_mayoritaria = sklearn_f1_score(y_true, mayoritaria, average="macro")

    assert resultado.attrs["a1_evaluable"] is True
    assert resultado.attrs["arm_mejor_baseline"] == "mayoritaria"
    assert resultado.attrs["f1_mejor_baseline"] == pytest.approx(f1_mayoritaria)
    assert resultado.attrs["a1_cumplida"] is bool(
        (f1_modelo - f1_mayoritaria) * 100.0 >= BARRA_ACEPTACION_A1_PUNTOS
    )
    assert "delta_modelo_vs_persistencia_pts" not in resultado.attrs


def test_evaluar_arms_not_evaluable_with_only_modelo_arm() -> None:
    """`modelo` alone (no baseline at all) cannot evaluate A1 -- there is
    nothing to compare against."""
    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    mask = np.ones(8, dtype=bool)

    predicciones = {"modelo": y_true.copy()}
    resultado = evaluar_arms(y_true, predicciones, mask)

    assert resultado.attrs["a1_evaluable"] is False
    assert "a1_cumplida" not in resultado.attrs
    assert "arm_mejor_baseline" not in resultado.attrs


def test_evaluar_arms_rejects_length_mismatch() -> None:
    y_true = np.array([0, 1, 2, 3])
    mask = np.array([True, True, False, False])
    with pytest.raises(ValueError):
        evaluar_arms(y_true, {"modelo": np.array([0, 1, 2])}, mask)


# ---------------------------------------------------------------------------
# 4.10 -- desglose_por_circuito (present either way)
# ---------------------------------------------------------------------------


def test_desglose_por_circuito_present_regardless_of_a1_outcome() -> None:
    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    mask = np.ones(8, dtype=bool)
    circuito = np.array(["C0", "C0", "C0", "C0", "C1", "C1", "C1", "C1"])
    predicciones = {
        "modelo": y_true.copy(),
        "persistencia": np.array([0, 1, 1, 0, 2, 3, 3, 2]),
    }
    resultado = desglose_por_circuito(y_true, predicciones, mask, circuito)

    assert set(resultado["circuito"]) == {"C0", "C1"}
    assert "macro_f1_modelo" in resultado.columns
    assert "macro_f1_persistencia" in resultado.columns
    assert (resultado["n"] == 4).all()


# ---------------------------------------------------------------------------
# 4.11 / 4.13 -- guardia_proxy_univariante_mil (A3)
# ---------------------------------------------------------------------------


def test_guardia_proxy_univariante_mil_wires_k_equals_4_and_voids_on_perfect_proxy() -> None:
    rng = np.random.default_rng(11)
    clase_observada = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    perfecto = np.array([0.0, 0.01, 5.0, 5.01, 10.0, 10.01, 15.0, 15.01])
    ruido = rng.normal(size=8)
    X_bag = np.column_stack([perfecto, ruido])
    features = ["perfecto", "ruido"]

    resultado = guardia_proxy_univariante_mil(clase_observada, X_bag, features, seed=0)

    assert resultado.attrs["ari_threshold"] == 0.8
    assert resultado.attrs["voided"] is True
    assert resultado.loc[resultado["feature"] == "perfecto", "ari"].iloc[0] > 0.8


# ---------------------------------------------------------------------------
# 4.12 / 4.13 -- grafo_por_grupo_si_no_colapsado (A4)
# ---------------------------------------------------------------------------


def test_grafo_por_grupo_si_no_colapsado_voids_on_collapse_and_builds_otherwise() -> None:
    edge_index = _tiny_edge_index()
    n_features = len(_FEATURES)
    labels = np.array([0, 0, 1, 1])

    gate_means_colapsado = np.ones((4, edge_index.n_edges), dtype=np.float64)
    resultado_colapsado = grafo_por_grupo_si_no_colapsado(
        gate_means_colapsado, edge_index, labels, n_features
    )
    assert resultado_colapsado["voided"] is True
    assert resultado_colapsado["grafos_por_grupo"] is None
    assert resultado_colapsado["colapso"]["is_collapsed"] is True

    rng = np.random.default_rng(4)
    gate_means_variado = rng.uniform(0.2, 1.8, size=(4, edge_index.n_edges))
    resultado_variado = grafo_por_grupo_si_no_colapsado(
        gate_means_variado, edge_index, labels, n_features
    )
    assert resultado_variado["voided"] is False
    assert resultado_variado["grafos_por_grupo"] is not None
    assert set(resultado_variado["grafos_por_grupo"].keys()) == {0, 1}


# ---------------------------------------------------------------------------
# 4.14 / 4.15 -- BagPredictor + predict_fn (simulator/SHAP contract, D7)
# ---------------------------------------------------------------------------


def test_bagpredictor_predict_singleton_bags_default_convention() -> None:
    predictor = _tiny_bag_predictor()
    X = np.random.default_rng(0).normal(size=(5, len(_FEATURES))).astype(np.float32)
    u = predictor.predict(X)
    assert u.shape == (5,)
    assert np.all(np.isfinite(u))


def test_bagpredictor_predict_class_uses_nearest_centroid() -> None:
    predictor = _tiny_bag_predictor()
    X = np.random.default_rng(1).normal(size=(4, len(_FEATURES))).astype(np.float32)
    n_obs = np.array([1.0, 2.0, 1.0, 3.0])
    clase = predictor.predict_class(X, n_obs)
    assert clase.shape == (4,)
    assert set(clase.tolist()) <= {0, 1, 2, 3}


def test_bagpredictor_predict_proba_returns_exactly_two_columns_prob_alto() -> None:
    predictor = _tiny_bag_predictor()
    X = np.random.default_rng(2).normal(size=(6, len(_FEATURES))).astype(np.float32)
    proba = predictor.predict_proba(X)

    assert proba.shape == (6, 2)
    np.testing.assert_allclose(proba.sum(axis=1), np.ones(6), atol=1e-6)
    assert np.all(proba >= 0.0) and np.all(proba <= 1.0)

    u = predictor.predict(X)
    n_obs = np.ones(6)
    distribucion_completa = distribucion_suave(n_obs, u, predictor.geometria)
    np.testing.assert_allclose(proba[:, 1], distribucion_completa[:, 3], atol=1e-6)


def test_predict_fn_matches_simulator_contract_shapes() -> None:
    predictor = _tiny_bag_predictor()
    X = np.random.default_rng(3).normal(size=(7, len(_FEATURES))).astype(np.float32)
    outputs = predict_fn(predictor, X, device="cpu", batch_size=1024)

    assert set(outputs.keys()) >= {"fused_probs", "predicted_classes"}
    assert outputs["fused_probs"].shape == (7, 4)
    assert outputs["predicted_classes"].shape == (7,)
    np.testing.assert_allclose(outputs["fused_probs"].sum(axis=1), np.ones(7), atol=1e-6)
    assert np.array_equal(
        outputs["predicted_classes"], np.argmax(outputs["fused_probs"], axis=1)
    ), "argmax(fused_probs) must equal the hard nearest-centroid class (D6 property)"


# ---------------------------------------------------------------------------
# 4.16 / 4.17 -- temporal block split (A6), diagnostic only
# ---------------------------------------------------------------------------


def test_particion_bloque_temporal_and_diagnostico_never_reselects_headline() -> None:
    keys = pd.DataFrame(
        {
            "CIRCUITO": ["C0"] * 8,
            "FID_VANO": ["V0"] * 8,
            "VENTANA": ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"],
        }
    )
    n_bags = 8
    counts = np.ones(n_bags, dtype=np.int64)
    offsets = np.arange(n_bags + 1, dtype=np.int64)
    instance_bag = np.arange(n_bags, dtype=np.int64)
    group = np.array(["C0|V0"] * n_bags, dtype=object)
    y = np.linspace(1.0, 2.0, n_bags)
    bag_index = BagIndex(
        keys=keys,
        instance_bag=instance_bag,
        offsets=offsets,
        counts=counts,
        y=y,
        group=group,
        instance_rows=np.arange(n_bags, dtype=np.int64),
    )

    train_mask, test_mask = particion_bloque_temporal(
        bag_index,
        ventanas_entrenamiento=[f"V{i}" for i in range(1, 7)],
        ventanas_prueba=["V7", "V8"],
    )
    assert train_mask.sum() == 6
    assert test_mask.sum() == 2
    assert not np.any(train_mask & test_mask)

    y_true = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    y_true_test = y_true[test_mask]
    predicciones = {"modelo": y_true_test.copy(), "persistencia": y_true_test.copy()}

    resultado_diagnostico = evaluar_diagnostico_temporal(y_true, predicciones, test_mask)
    assert resultado_diagnostico.attrs["es_diagnostico"] is True

    resultado_headline = evaluar_arms(y_true, predicciones, test_mask)
    assert "es_diagnostico" not in resultado_headline.attrs
