"""Unit tests for the criticality-representation interpretability + acceptance-gate
machinery (`src/chec_impacto/interpretability/mgcecdl_graph.py`).

Covers PR2 of notebook-12-criticality-representation: per-vano gate pooling,
the per-cluster edge-deviation table (with runtime climate-family collapse),
the anti-collapse diagnostics (variance/rank, degree-preserving permutation
control), the single-feature-proxy guard, the chronological p70 split, the
per-vano future-UITI_VANO validation target, the persistence diagnostic
(D8), and the mandatory no-graph KMeans baseline + data-driven K sweep. See:
  - spec: sdd/notebook-12-criticality-representation/spec (capabilities
    `notebook-local-variable-selection`, `criticality-evidence-protocol`,
    `graph-regime-clustering`)
  - design: sdd/notebook-12-criticality-representation/design (D3, D4, D7, D8)

All fixtures are tiny synthetic data -- no real training runs (PR3 wires the
end-to-end notebook execution).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chec_impacto.models.mgcecdl_graph import GraphEdgeIndex, construir_edge_index

from chec_impacto.interpretability.mgcecdl_graph import (
    agrupar_gates_por_vano,
    asociacion_criticidad,
    assert_fecha_excluded_from_features,
    control_permutacion_grados,
    corregir_benjamini_hochberg,
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

INTERPRETABILITY_MODULE_PATH = Path(
    "src/chec_impacto/interpretability/mgcecdl_graph.py"
)

_FEATURES = [
    "prep_2",
    "prep_1",
    "prep_0",
    "COD_CAUSA",
    "FECHA_OPERACION_TRF",
    "LONG_CRUCETA",
    "UITI_VANO",
]
_EDGES = [
    {"source": "prep_2", "target": "prep_1", "weight": 0.90},
    {"source": "prep_1", "target": "prep_0", "weight": 0.90},
    {"source": "prep_0", "target": "COD_CAUSA", "weight": 0.85},
    {"source": "COD_CAUSA", "target": "UITI_VANO", "weight": 0.70},
]


def _tiny_edge_index() -> GraphEdgeIndex:
    positions = {name: index for index, name in enumerate(_FEATURES)}
    adjacency = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for edge in _EDGES:
        adjacency[positions[edge["source"]], positions[edge["target"]]] = edge["weight"]
    return construir_edge_index(adjacency, _FEATURES, _EDGES)


# ---------------------------------------------------------------------------
# 2.1 / 2.3 -- split_cronologico_p70 / FECHA-excluded assertion
# ---------------------------------------------------------------------------


def test_split_cronologico_p70_derives_cut_not_literal() -> None:
    """The cut must be COMPUTED as the p70 quantile of `fechas`, never a
    hardcoded date -- confirmed by two independent, differently-shaped date
    ranges producing two different cuts."""
    source = INTERPRETABILITY_MODULE_PATH.read_text(encoding="utf-8")
    assert "2026-03-11" not in source, (
        "split_cronologico_p70 must derive its cut at runtime, never hardcode the date "
        "measured on the real dataset"
    )

    fechas_a = pd.date_range("2025-01-01", periods=100, freq="D")
    past_a, future_a, cut_a = split_cronologico_p70(fechas_a)

    fechas_b = pd.date_range("2020-06-01", periods=200, freq="D")
    past_b, future_b, cut_b = split_cronologico_p70(fechas_b)

    assert cut_a != cut_b, "different input date ranges must produce different computed cuts"
    assert past_a.sum() + future_a.sum() == len(fechas_a)
    assert past_b.sum() + future_b.sum() == len(fechas_b)

    # p70 split: strictly less than 100% and strictly more than 0% should sit in the past.
    assert 0 < past_a.sum() < len(fechas_a)
    fraction_past = past_a.sum() / len(fechas_a)
    assert 0.55 < fraction_past < 0.85


def test_fecha_excluded_from_features_assertion() -> None:
    assert_fecha_excluded_from_features(["a", "b", "UITI_VANO"])  # must not raise

    with pytest.raises(ValueError):
        assert_fecha_excluded_from_features(["a", "FECHA", "UITI_VANO"])


# ---------------------------------------------------------------------------
# 2.5 -- agrupar_gates_por_vano
# ---------------------------------------------------------------------------


def test_agrupar_gates_por_vano_pooling_shape() -> None:
    n_samples = 12
    n_edges = 3
    rng = np.random.default_rng(0)
    gates = rng.normal(size=(n_samples, n_edges)).astype(np.float32)
    # 4 distinct vanos, 3 samples each.
    circuito = np.array(["C1"] * 6 + ["C2"] * 6)
    fid_vano = np.array(([1] * 3 + [2] * 3) * 2)

    gate_means, vano_index = agrupar_gates_por_vano(gates, circuito, fid_vano)

    assert gate_means.shape == (4, n_edges)
    assert len(vano_index) == 4
    assert set(vano_index.columns) >= {"CIRCUITO", "FID_VANO"}

    # Manually verify one group's mean.
    mask = (circuito == "C1") & (fid_vano == 1)
    expected_mean = gates[mask].mean(axis=0)
    row_position = vano_index[
        (vano_index["CIRCUITO"] == "C1") & (vano_index["FID_VANO"] == 1)
    ].index[0]
    np.testing.assert_allclose(gate_means[row_position], expected_mean, rtol=1e-5)


# ---------------------------------------------------------------------------
# 2.7 / 2.9 -- tabla_desviacion_aristas (family collapse) / degree-zero table
# ---------------------------------------------------------------------------


def test_tabla_desviacion_aristas_columns_and_family_collapse() -> None:
    edge_index = _tiny_edge_index()
    n_vano = 20
    rng = np.random.default_rng(1)
    gate_means = rng.uniform(0.5, 1.5, size=(n_vano, edge_index.n_edges)).astype(np.float32)
    cluster_labels = np.array([0] * 10 + [1] * 10)

    collapsed = tabla_desviacion_aristas(
        gate_means, edge_index, cluster_labels, colapsar_familias=True
    )
    expanded = tabla_desviacion_aristas(
        gate_means, edge_index, cluster_labels, colapsar_familias=False
    )

    required_columns = {
        "source",
        "target",
        "expert_weight",
        "cluster_mean_gate",
        "population_mean_gate",
        "delta",
        "abs_delta_rank",
    }
    assert required_columns.issubset(collapsed.columns)

    # The intra-family lag edge (prep_1 -> prep_0) collapses to ONE row per cluster
    # when colapsar_familias=True; the cross-variable edges are always listed
    # individually in both variants.
    n_clusters = len(np.unique(cluster_labels))
    assert len(collapsed) == len(expanded) - n_clusters  # one fewer row per cluster
    assert not any(
        row["source"] == "prep_1" and row["target"] == "prep_0"
        for _, row in collapsed.iterrows()
    )
    assert any(
        row["source"] == "COD_CAUSA" and row["target"] == "UITI_VANO"
        for _, row in collapsed.iterrows()
    ), "cross-variable couplings must always be listed individually"


def test_no_duplicated_climate_family_literal_list() -> None:
    """The family-collapse logic must read `CLIMATE_FAMILIES` from
    `chec_impacto.data.graph` at runtime, never duplicate the literal list."""
    source = INTERPRETABILITY_MODULE_PATH.read_text(encoding="utf-8")
    assert "from chec_impacto.data.graph import" in source
    assert "CLIMATE_FAMILIES" in source
    # None of the individual family literals should be hardcoded as a fresh tuple here.
    assert '"prep"' not in source and "'prep'" not in source


def test_degree_zero_features_reported_ungatable() -> None:
    features = [*_FEATURES, "FECHA_OPERACION_TRF_dup", "LONG_CRUCETA"]
    # FECHA_OPERACION_TRF is already in _FEATURES with degree 0 (no edges touch it);
    # LONG_CRUCETA (appended) also has degree 0.
    edge_index = _tiny_edge_index()

    degree_table = tabla_grado_features(features, edge_index)

    ungatable = degree_table[degree_table["ungatable"]]["feature"].tolist()
    assert "FECHA_OPERACION_TRF" in ungatable
    assert "LONG_CRUCETA" in ungatable
    for feature in ("prep_1", "prep_0", "COD_CAUSA", "UITI_VANO"):
        assert feature not in ungatable


# ---------------------------------------------------------------------------
# 2.11 -- estadistico_colapso
# ---------------------------------------------------------------------------


def test_estadistico_colapso_flags_constant_tensor() -> None:
    n_vano, n_edges = 30, 5

    constant_gates = np.ones((n_vano, n_edges), dtype=np.float64)
    constant_stats = estadistico_colapso(constant_gates)
    assert constant_stats["is_collapsed"] is True
    assert constant_stats["variance"] == pytest.approx(0.0, abs=1e-9)
    assert constant_stats["effective_rank"] <= 1.0 + 1e-6

    rng = np.random.default_rng(2)
    varied_gates = rng.uniform(0.2, 1.8, size=(n_vano, n_edges))
    varied_stats = estadistico_colapso(varied_gates)
    assert varied_stats["is_collapsed"] is False
    assert varied_stats["variance"] > constant_stats["variance"]
    assert varied_stats["effective_rank"] > constant_stats["effective_rank"]


# ---------------------------------------------------------------------------
# 2.13 / 2.15 -- control_permutacion_grados / full-retrain wiring
# ---------------------------------------------------------------------------


def test_control_permutacion_grados_preserves_degree_sequence() -> None:
    rng = np.random.default_rng(4)
    n = 12
    adjacency = np.zeros((n, n), dtype=np.float32)
    # A moderately connected directed graph so swaps have room to happen.
    for source in range(n):
        targets = rng.choice([t for t in range(n) if t != source], size=3, replace=False)
        for target in targets:
            adjacency[source, target] = rng.uniform(0.3, 1.0)

    permuted = control_permutacion_grados(adjacency, seed=7)

    original_out_degree = (adjacency != 0).sum(axis=1)
    original_in_degree = (adjacency != 0).sum(axis=0)
    permuted_out_degree = (permuted != 0).sum(axis=1)
    permuted_in_degree = (permuted != 0).sum(axis=0)

    np.testing.assert_array_equal(original_out_degree, permuted_out_degree)
    np.testing.assert_array_equal(original_in_degree, permuted_in_degree)
    assert not np.array_equal(adjacency != 0, permuted != 0), (
        "the permutation control must actually rewire edge placement, not return a copy"
    )


def test_permutation_control_requires_full_retrain() -> None:
    call_log: list[int] = []

    def _stub_entrenar(model, loss_fn, X_past, **kwargs):
        call_log.append(id(model))
        return {"model": model, "reconstruction_loss_raw": 0.1}

    def _stub_build_model(adjacency, edge_index):
        return object()

    def _stub_build_loss():
        return object()

    adjacency = _tiny_edge_index_adjacency()
    features = _FEATURES

    result_1 = ejecutar_control_permutacion_grados(
        adjacency,
        features,
        build_model_fn=_stub_build_model,
        build_loss_fn=_stub_build_loss,
        X_past=np.zeros((4, len(features)), dtype=np.float32),
        seed=1,
        entrenar_fn=_stub_entrenar,
        epochs=1,
    )
    result_2 = ejecutar_control_permutacion_grados(
        adjacency,
        features,
        build_model_fn=_stub_build_model,
        build_loss_fn=_stub_build_loss,
        X_past=np.zeros((4, len(features)), dtype=np.float32),
        seed=2,
        entrenar_fn=_stub_entrenar,
        epochs=1,
    )

    assert len(call_log) == 2, "each call must trigger exactly one fresh retrain"
    assert call_log[0] != call_log[1], "each call must build a brand-new model, never reuse cache"
    assert "permuted_adjacency" in result_1 and "permuted_adjacency" in result_2


def _tiny_edge_index_adjacency() -> np.ndarray:
    positions = {name: index for index, name in enumerate(_FEATURES)}
    adjacency = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for edge in _EDGES:
        adjacency[positions[edge["source"]], positions[edge["target"]]] = edge["weight"]
    return adjacency


# ---------------------------------------------------------------------------
# 2.17 -- guardia_proxy_univariante (single-feature-proxy guard)
# ---------------------------------------------------------------------------


def test_guardia_proxy_univariante_flags_uiti_vano() -> None:
    n_samples = 60
    rng = np.random.default_rng(5)
    uiti_vano_column = np.concatenate(
        [rng.normal(0.0, 0.05, size=30), rng.normal(5.0, 0.05, size=30)]
    )
    other_column = rng.normal(size=n_samples)
    X = np.column_stack([other_column, uiti_vano_column])
    features = ["other_feature", "UITI_VANO"]

    # Cluster labels built directly from UITI_VANO's own bimodal structure --
    # a perfect proxy by construction.
    cluster_labels = (uiti_vano_column > 2.5).astype(int)

    guard_table = guardia_proxy_univariante(cluster_labels, X, features, k=2, seed=0)

    assert set(guard_table["feature"]) == set(features)
    assert "UITI_VANO" in guard_table["feature"].values
    uiti_row = guard_table.loc[guard_table["feature"] == "UITI_VANO"].iloc[0]
    assert uiti_row["ari"] > 0.8
    assert guard_table.attrs["voided"] is True
    assert guard_table.attrs["max_ari"] > 0.8


# ---------------------------------------------------------------------------
# 2.19 / 2.21 -- uiti_futuro_por_vano / diagnostico_persistencia (D8)
# ---------------------------------------------------------------------------


def _synthetic_df_original_copy() -> pd.DataFrame:
    rng = np.random.default_rng(6)
    n_rows = 40
    fechas = pd.to_datetime(
        ["2026-01-01"] * 20 + ["2026-05-01"] * 20
    )
    return pd.DataFrame(
        {
            "CIRCUITO": ["C1"] * n_rows,
            "FID_VANO": ([1] * 10 + [2] * 10) * 2,
            "FECHA": fechas,
            "UITI_VANO": rng.uniform(0, 5, size=n_rows),
            "COD_CAUSA": (["CAUSA_A"] * 5 + ["CAUSA_B"] * 5) * 4,
        }
    )


def test_uiti_futuro_por_vano_uses_future_mask_only() -> None:
    df = _synthetic_df_original_copy()
    future_mask = (df["FECHA"] >= "2026-05-01").to_numpy()

    result = uiti_futuro_por_vano(df, future_mask)

    expected = (
        df.loc[future_mask]
        .groupby(["CIRCUITO", "FID_VANO"], sort=False)["UITI_VANO"]
        .sum()
    )
    for _, row in result.iterrows():
        key = (row["CIRCUITO"], row["FID_VANO"])
        assert row["UITI_VANO_futuro_acumulado"] == pytest.approx(expected[key])

    # Rows entirely from the PAST window must never leak into the accumulation.
    past_only_sum = df.loc[~future_mask, "UITI_VANO"].sum()
    total_future_reported = result["UITI_VANO_futuro_acumulado"].sum()
    assert total_future_reported == pytest.approx(df.loc[future_mask, "UITI_VANO"].sum())
    assert total_future_reported != pytest.approx(past_only_sum + total_future_reported - 1e9)


def test_diagnostico_persistencia_reports_three_explanations() -> None:
    df = _synthetic_df_original_copy()
    past_mask = (df["FECHA"] < "2026-05-01").to_numpy()
    future_mask = ~past_mask

    result = diagnostico_persistencia(df, past_mask, future_mask)

    assert "regression_to_mean_correlation" in result
    assert "intervention_by_cod_causa" in result
    assert isinstance(result["intervention_by_cod_causa"], pd.DataFrame)
    assert "censoring_correlation_unrestricted" in result
    assert "primary_correlation_both_windows" in result

    # The correlation must be COMPUTED, never hardcoded to the value measured
    # on the real dataset.
    source = INTERPRETABILITY_MODULE_PATH.read_text(encoding="utf-8")
    assert "-0.108" not in source


# ---------------------------------------------------------------------------
# 2.23 / 2.25 -- no-graph KMeans baseline / data-driven K sweep
# ---------------------------------------------------------------------------


def test_kmeans_no_graph_baseline_available() -> None:
    rng = np.random.default_rng(8)
    n_samples = 40
    n_features = 4
    X = rng.normal(size=(n_samples, n_features))
    circuito = np.array(["C1"] * n_samples)
    fid_vano = np.repeat(np.arange(10), 4)
    features = [f"f{i}" for i in range(n_features)]

    labels, vano_index = linea_base_sin_grafo(X, features, circuito, fid_vano, k=3, seed=0)

    assert labels.shape[0] == len(vano_index) == 10
    assert set(np.unique(labels)).issubset({0, 1, 2})

    labels_repeat, _ = linea_base_sin_grafo(X, features, circuito, fid_vano, k=3, seed=0)
    np.testing.assert_array_equal(labels, labels_repeat)


def test_data_driven_k_never_silently_forced() -> None:
    rng = np.random.default_rng(9)
    # 4 well-separated synthetic blobs over 6-D gate space.
    centers = np.array(
        [
            [0, 0, 0, 0, 0, 0],
            [10, 10, 0, 0, 0, 0],
            [0, 0, 10, 10, 0, 0],
            [0, 0, 0, 0, 10, 10],
        ],
        dtype=float,
    )
    blocks = [
        center + rng.normal(scale=0.3, size=(15, 6)) for center in centers
    ]
    gate_means = np.vstack(blocks)

    result = seleccionar_k_datos(
        gate_means, k_range=range(2, 11), seeds=(0, 1, 2, 3, 4)
    )

    assert result["k_raw"] == 4
    assert result["tier_view"] is None, (
        "raw K must never be silently overwritten/replaced by a forced 3-4 tier view"
    )
    assert set(result["silhouette_by_k"].keys()) == set(range(2, 11))
    assert set(result["ari_by_k"].keys()) == set(range(2, 11))
    assert result["ari_by_k"][4] > 0.9  # perfectly separated blobs -> near-perfect cross-seed ARI


# ---------------------------------------------------------------------------
# Cluster-criticality statistical association (Kruskal-Wallis + epsilon-squared
# + BH-corrected Dunn). This is the evidence for the user's requirement that
# clusters relate to accumulated-UITI patterns, so it lives in tested library
# code rather than in an untested notebook cell.
# ---------------------------------------------------------------------------


def _separated_groups(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    labels = np.repeat([0, 1, 2], 60)
    values = np.concatenate(
        [
            rng.normal(10.0, 1.0, 60),
            rng.normal(20.0, 1.0, 60),
            rng.normal(30.0, 1.0, 60),
        ]
    )
    return labels, values


def test_asociacion_criticidad_reports_kruskal_epsilon_and_dunn() -> None:
    rng = np.random.default_rng(0)
    labels, values = _separated_groups(rng)

    result = asociacion_criticidad(labels, values)

    assert {"H", "p_value", "epsilon_squared", "n", "k", "pairwise"} <= set(result)
    assert result["k"] == 3
    assert result["n"] == labels.size
    assert result["p_value"] < 1e-10
    assert result["epsilon_squared"] > 0.5

    pairwise = result["pairwise"]
    assert len(pairwise) == 3  # C(3,2)
    assert {"cluster_a", "cluster_b", "z", "p_value", "p_value_bh"} <= set(pairwise.columns)
    assert (pairwise["p_value_bh"] >= pairwise["p_value"] - 1e-12).all()
    assert (pairwise["p_value_bh"] <= 1.0).all()


def test_epsilon_squared_matches_H_over_n_minus_one() -> None:
    rng = np.random.default_rng(1)
    labels, values = _separated_groups(rng)

    result = asociacion_criticidad(labels, values)

    # Tomczak & Tomczak (2014): eps^2 = H / ((n^2 - 1)/(n + 1)) = H / (n - 1).
    assert result["epsilon_squared"] == pytest.approx(result["H"] / (result["n"] - 1))
    assert 0.0 <= result["epsilon_squared"] <= 1.0


def test_dunn_z_squared_equals_kruskal_H_for_two_groups() -> None:
    # Strong correctness anchor: with exactly two groups the Kruskal-Wallis H
    # statistic equals the square of Dunn's z. If the tie correction or the
    # rank-mean standard error were wrong, this identity would break.
    rng = np.random.default_rng(2)
    labels = np.repeat([0, 1], 50)
    values = np.concatenate([rng.normal(0.0, 1.0, 50), rng.normal(1.5, 1.0, 50)])

    result = asociacion_criticidad(labels, values)

    assert len(result["pairwise"]) == 1
    z = float(result["pairwise"]["z"].iloc[0])
    assert z**2 == pytest.approx(result["H"], rel=1e-9)


def test_dunn_handles_ties_without_breaking_the_two_group_identity() -> None:
    # Heavily tied data exercises the tie-correction branch; the identity must
    # still hold, which a missing correction term would violate.
    rng = np.random.default_rng(3)
    labels = np.repeat([0, 1], 40)
    values = np.concatenate(
        [rng.integers(0, 3, 40).astype(float), rng.integers(1, 4, 40).astype(float)]
    )

    result = asociacion_criticidad(labels, values)

    z = float(result["pairwise"]["z"].iloc[0])
    assert z**2 == pytest.approx(result["H"], rel=1e-9)


def test_identical_groups_show_no_association() -> None:
    rng = np.random.default_rng(4)
    labels = np.repeat([0, 1, 2], 50)
    values = rng.normal(5.0, 1.0, 150)  # one distribution, arbitrary labels

    result = asociacion_criticidad(labels, values)

    assert result["p_value"] > 0.05
    assert result["epsilon_squared"] < 0.05
    assert (result["pairwise"]["p_value_bh"] > 0.05).all()


def test_benjamini_hochberg_is_monotone_and_bounded() -> None:
    raw = np.array([0.001, 0.008, 0.039, 0.041, 0.9])

    adjusted = corregir_benjamini_hochberg(raw)

    assert adjusted.shape == raw.shape
    assert (adjusted >= raw - 1e-12).all()
    assert (adjusted <= 1.0).all()
    # BH adjusted p-values are non-decreasing in the raw ordering.
    order = np.argsort(raw)
    assert np.all(np.diff(adjusted[order]) >= -1e-12)


def test_asociacion_criticidad_rejects_single_cluster() -> None:
    with pytest.raises(ValueError, match="at least two"):
        asociacion_criticidad(np.zeros(20, dtype=int), np.arange(20, dtype=float))
