"""Interpretability and acceptance-gate machinery for the per-sample edge-gate
criticality representation (`chec_impacto.models.mgcecdl_graph`).

Notebook 12's clusters are per-vano graph regimes over the `E`-dimensional
gate vector `g_bar`. This module builds the evidence protocol that keeps
that clustering honest:

- per-vano gate pooling (`agrupar_gates_por_vano`) and the mandatory
  no-graph baseline (`linea_base_sin_grafo`);
- the per-cluster edge-deviation table with runtime climate-family collapse
  (`tabla_desviacion_aristas`) and the degree-zero ungatable-feature report
  (`tabla_grado_features`);
- the four-criterion anti-collapse acceptance gate's building blocks:
  variance/effective-rank (`estadistico_colapso`), the degree-preserving
  permutation control with a MANDATORY full retrain
  (`control_permutacion_grados`, `ejecutar_control_permutacion_grados`), and
  the data-driven K sweep (`seleccionar_k_datos`);
- the single-feature-proxy guard (`guardia_proxy_univariante`);
- the chronological p70 partition (`split_cronologico_p70`) and its
  leakage guard (`assert_fecha_excluded_from_features`);
- the per-vano FUTURE accumulated validation target
  (`uiti_futuro_por_vano`) and the persistence diagnostic
  (`diagnostico_persistencia`, D8).

See:
  - spec: sdd/notebook-12-criticality-representation/spec (capabilities
    `notebook-local-variable-selection`, `criticality-evidence-protocol`,
    `graph-regime-clustering`)
  - design: sdd/notebook-12-criticality-representation/design (D3, D4, D7, D8)

Nothing here trains a model directly (`entrenar_gated_autoencoder` is
imported lazily, only inside `ejecutar_control_permutacion_grados`, so this
module stays importable and cheap even when torch model construction is not
needed) -- notebook 12's actual end-to-end wiring is a PR3 concern.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import kruskal, norm, rankdata
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from chec_impacto.data.graph import CLIMATE_FAMILIES
from chec_impacto.models.mgcecdl_graph import GraphEdgeIndex

_MIN_MINORITY_CLUSTER_FRACTION = 0.01


# ---------------------------------------------------------------------------
# Chronological split + leakage guard
# ---------------------------------------------------------------------------


def split_cronologico_p70(
    fechas: Sequence[Any],
) -> tuple[np.ndarray, np.ndarray, np.datetime64]:
    """Chronological 70th-percentile split: `past_mask, future_mask, cut`.

    `cut` is COMPUTED as the p70 quantile of `fechas` at runtime -- never a
    hardcoded literal date. The notebook that calls this on the real dataset
    reports the resulting `cut` explicitly rather than assuming any fixed
    value.
    """
    fecha_series = pd.to_datetime(pd.Series(list(fechas)))
    if fecha_series.empty:
        raise ValueError("fechas must be non-empty.")

    fecha_values = fecha_series.to_numpy()
    epoch_nanoseconds = fecha_values.astype("datetime64[ns]").astype(np.int64)
    p70_quantile = 0.7  # p70: the chronological cut sits at this percentile.
    cut_nanoseconds = int(np.quantile(epoch_nanoseconds, p70_quantile))
    cut = np.datetime64(cut_nanoseconds, "ns")

    past_mask = fecha_values <= cut
    future_mask = fecha_values > cut
    return past_mask, future_mask, cut


def assert_fecha_excluded_from_features(features: Sequence[str]) -> None:
    """Raise if `"FECHA"` is present among model features (leakage guard)."""
    if "FECHA" in list(features):
        raise ValueError(
            "'FECHA' must not be present among model features -- it is a chronological "
            "leakage vector, never an input to the gate encoder."
        )


# ---------------------------------------------------------------------------
# Per-vano pooling
# ---------------------------------------------------------------------------


def agrupar_gates_por_vano(
    values: np.ndarray,
    circuito: Sequence[Any],
    fid_vano: Sequence[Any],
) -> tuple[np.ndarray, pd.DataFrame]:
    """Pool per-sample per-edge values to per-vano means, grouped by
    `(CIRCUITO, FID_VANO)`.

    The model runs per EVENT ROW; clusters are per VANO -- this is the
    pooling step that bridges the two. Generic over any `(n_samples, n_dims)`
    array, so it is reused by `linea_base_sin_grafo` to pool standardized raw
    features for the mandatory no-graph baseline.
    """
    values = np.asarray(values)
    if values.ndim != 2:
        raise ValueError(f"values must be 2-D (n_samples, n_dims); got shape {values.shape}.")

    circuito_array = np.asarray(circuito)
    fid_vano_array = np.asarray(fid_vano)
    if circuito_array.shape[0] != values.shape[0] or fid_vano_array.shape[0] != values.shape[0]:
        raise ValueError("circuito/fid_vano must have the same length as values' first axis.")

    frame = pd.DataFrame(values, columns=[f"dim_{i}" for i in range(values.shape[1])])
    frame.insert(0, "FID_VANO", fid_vano_array)
    frame.insert(0, "CIRCUITO", circuito_array)

    grouped = frame.groupby(["CIRCUITO", "FID_VANO"], sort=False).mean()
    pooled_values = grouped.to_numpy()
    vano_index = grouped.index.to_frame(index=False).reset_index(drop=True)
    return pooled_values, vano_index


def linea_base_sin_grafo(
    X: np.ndarray,
    features: Sequence[str],
    circuito: Sequence[Any],
    fid_vano: Sequence[Any],
    k: int,
    seed: int = 42,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Mandatory no-graph baseline: KMeans on the per-vano mean of
    STANDARDIZED raw features, using the SAME K and seed protocol as the
    gate-based clustering -- spec requirement "Mandatory no-graph baseline".
    """
    del features  # kept for interface symmetry / future column-level reporting
    X = np.asarray(X, dtype=np.float64)
    standardized = StandardScaler().fit_transform(X)
    vano_means, vano_index = agrupar_gates_por_vano(standardized, circuito, fid_vano)

    kmeans = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(vano_means)
    return kmeans.labels_, vano_index


# ---------------------------------------------------------------------------
# Per-cluster edge-deviation table + degree-zero feature report
# ---------------------------------------------------------------------------


def _climate_family_of(feature_name: str) -> str | None:
    for family in CLIMATE_FAMILIES:
        if feature_name == family or feature_name.startswith(f"{family}_"):
            return family
    return None


def tabla_desviacion_aristas(
    gate_means: np.ndarray,
    edge_index: GraphEdgeIndex,
    cluster_labels: np.ndarray,
    colapsar_familias: bool = True,
) -> pd.DataFrame:
    """Per-cluster edge-deviation table.

    Columns: `cluster | source | target | expert_weight | cluster_mean_gate
    | population_mean_gate | delta | abs_delta | abs_delta_rank`.

    When `colapsar_familias=True`, intra-family climate lag chains --
    determined at RUNTIME from `CLIMATE_FAMILIES` (`chec_impacto.data.graph`),
    never a duplicated literal list -- collapse into one summary row per
    family per cluster (with `n_collapsed_edges`); cross-variable couplings
    are always listed individually.
    """
    gate_means = np.asarray(gate_means)
    cluster_labels = np.asarray(cluster_labels)
    if gate_means.shape[0] != cluster_labels.shape[0]:
        raise ValueError(
            "gate_means and cluster_labels must have the same number of rows (vanos)."
        )
    if gate_means.shape[1] != edge_index.n_edges:
        raise ValueError("gate_means column count must equal edge_index.n_edges.")

    population_mean = gate_means.mean(axis=0)
    rows: list[dict[str, Any]] = []

    for cluster in sorted(np.unique(cluster_labels)):
        cluster_mask = cluster_labels == cluster
        cluster_mean = gate_means[cluster_mask].mean(axis=0)

        family_edge_positions: dict[str, list[int]] = {}
        for edge_position, (source, target) in enumerate(edge_index.names):
            source_family = _climate_family_of(source)
            target_family = _climate_family_of(target)
            is_intra_family_lag_chain = (
                colapsar_familias
                and source_family is not None
                and source_family == target_family
            )
            if is_intra_family_lag_chain:
                family_edge_positions.setdefault(source_family, []).append(edge_position)
                continue

            delta = float(cluster_mean[edge_position] - population_mean[edge_position])
            rows.append(
                {
                    "cluster": cluster,
                    "source": source,
                    "target": target,
                    "expert_weight": float(edge_index.weights[edge_position]),
                    "cluster_mean_gate": float(cluster_mean[edge_position]),
                    "population_mean_gate": float(population_mean[edge_position]),
                    "delta": delta,
                    "abs_delta": abs(delta),
                }
            )

        for family, positions in family_edge_positions.items():
            cluster_family_mean = float(cluster_mean[positions].mean())
            population_family_mean = float(population_mean[positions].mean())
            delta = cluster_family_mean - population_family_mean
            rows.append(
                {
                    "cluster": cluster,
                    "source": f"{family}_lag_chain",
                    "target": f"{family}_lag_chain",
                    "expert_weight": float(edge_index.weights[positions].mean()),
                    "cluster_mean_gate": cluster_family_mean,
                    "population_mean_gate": population_family_mean,
                    "delta": delta,
                    "abs_delta": abs(delta),
                    "n_collapsed_edges": len(positions),
                }
            )

    result = pd.DataFrame(rows)
    result["abs_delta_rank"] = (
        result.groupby("cluster")["abs_delta"].rank(ascending=False, method="first").astype(int)
    )
    return result.sort_values(["cluster", "abs_delta_rank"]).reset_index(drop=True)


def tabla_grado_features(
    features: Sequence[str],
    edge_index: GraphEdgeIndex,
) -> pd.DataFrame:
    """Per-feature graph degree (in + out), flagging degree-0 features as
    `ungatable` -- spec capability `notebook-local-variable-selection`,
    requirement "Degree-zero feature reporting".

    A feature outside `edge_index`'s support entirely (e.g.
    `FECHA_OPERACION_TRF`, `LONG_CRUCETA`) can never be reached by a
    per-sample gate.
    """
    feature_list = list(features)
    out_degree = {name: 0 for name in feature_list}
    in_degree = {name: 0 for name in feature_list}
    for source, target in edge_index.names:
        if source in out_degree:
            out_degree[source] += 1
        if target in in_degree:
            in_degree[target] += 1

    rows = []
    for name in feature_list:
        degree = out_degree[name] + in_degree[name]
        ungatable = degree == 0
        rows.append(
            {
                "feature": name,
                "out_degree": out_degree[name],
                "in_degree": in_degree[name],
                "degree": degree,
                "ungatable": ungatable,
                "note": (
                    "no edge touches this feature; per-sample gates cannot reach it"
                    if ungatable
                    else ""
                ),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Anti-collapse acceptance-gate building blocks
# ---------------------------------------------------------------------------


def estadistico_colapso(
    gate_means: np.ndarray,
    near_constant_std_threshold: float = 1e-6,
) -> dict[str, Any]:
    """Variance + effective-rank collapse diagnostic (acceptance criterion 1).

    `variance = mean_e[Var_vano(g_bar_e)]`. `effective_rank` is the
    participation ratio of the `(n_vano, E)` gate matrix's singular values
    (`(sum sv^2)^2 / sum(sv^4)`), which evaluates to ~1.0 for a matrix whose
    variation lives along a single direction (i.e. every vano is gated
    alike) and grows toward `min(n_vano, E)` as gate variation spreads
    across more independent directions.
    """
    gate_means = np.asarray(gate_means, dtype=np.float64)
    if gate_means.ndim != 2:
        raise ValueError(
            f"gate_means must be 2-D (n_vano, n_edges); got shape {gate_means.shape}."
        )

    n_vano = gate_means.shape[0]
    if n_vano > 1:
        per_edge_variance = gate_means.var(axis=0, ddof=1)
        per_edge_std = gate_means.std(axis=0, ddof=1)
    else:
        per_edge_variance = np.zeros(gate_means.shape[1])
        per_edge_std = np.zeros(gate_means.shape[1])

    variance = float(per_edge_variance.mean())

    centered = gate_means - gate_means.mean(axis=0, keepdims=True)
    singular_values = np.linalg.svd(centered, compute_uv=False)
    squared_singular_values = singular_values**2
    total_energy = squared_singular_values.sum()
    if total_energy <= 0:
        effective_rank = 0.0
    else:
        effective_rank = float(
            (squared_singular_values.sum() ** 2) / np.sum(squared_singular_values**2)
        )

    is_near_constant = bool(np.all(per_edge_std < near_constant_std_threshold))
    is_collapsed = is_near_constant or effective_rank <= 1.0 + 1e-9

    return {
        "variance": variance,
        "effective_rank": effective_rank,
        "per_edge_variance": per_edge_variance,
        "is_collapsed": is_collapsed,
    }


def control_permutacion_grados(
    A: np.ndarray,
    seed: int,
    n_swap_attempts: int | None = None,
) -> np.ndarray:
    """Degree-preserving double-edge-swap permutation control (acceptance
    criterion 3).

    Repeatedly picks two existing edges `(u, v)` and `(x, y)` and swaps their
    targets to `(u, y)` and `(x, v)` whenever that would not create a
    self-loop or a duplicate edge -- this preserves EVERY node's out-degree
    and in-degree exactly while rewiring which nodes connect to which.
    """
    A = np.asarray(A)
    n = A.shape[0]
    if A.shape != (n, n):
        raise ValueError("A must be square.")

    edges = [(i, j, float(A[i, j])) for i in range(n) for j in range(n) if A[i, j] != 0.0]
    if len(edges) < 2:
        return A.copy()

    rng = np.random.default_rng(seed)
    edge_set = {(source, target) for source, target, _ in edges}
    if n_swap_attempts is None:
        n_swap_attempts = 10 * len(edges)

    for _ in range(n_swap_attempts):
        first_index, second_index = rng.integers(0, len(edges), size=2)
        if first_index == second_index:
            continue
        u, v, weight_uv = edges[first_index]
        x, y, weight_xy = edges[second_index]
        if v == y or u == y or x == v:
            continue
        if (u, y) in edge_set or (x, v) in edge_set:
            continue

        edge_set.discard((u, v))
        edge_set.discard((x, y))
        edge_set.add((u, y))
        edge_set.add((x, v))
        edges[first_index] = (u, y, weight_uv)
        edges[second_index] = (x, v, weight_xy)

    permuted = np.zeros_like(A)
    for source, target, weight in edges:
        permuted[source, target] = weight
    return permuted


def _edge_index_from_adjacency(A: np.ndarray, features: Sequence[str]) -> GraphEdgeIndex:
    """Build a `GraphEdgeIndex` directly from an adjacency's nonzero entries.

    Unlike `construir_edge_index`, this needs no `preserved_edges` name
    list: after `control_permutacion_grados` only the `(i, j)` POSITIONS
    moved, so feature identity and edge weight are read straight from the
    matrix.
    """
    feature_list = list(features)
    A = np.asarray(A)
    rows, cols = np.nonzero(A)
    pairs = np.stack([rows, cols], axis=1).astype(np.int64)
    names = tuple((feature_list[i], feature_list[j]) for i, j in zip(rows, cols))
    weights = A[rows, cols].astype(np.float32)
    return GraphEdgeIndex(pairs=pairs, names=names, weights=weights)


def ejecutar_control_permutacion_grados(
    A: np.ndarray,
    features: Sequence[str],
    build_model_fn: Callable[[np.ndarray, GraphEdgeIndex], Any],
    build_loss_fn: Callable[[], Any],
    X_past: np.ndarray,
    seed: int,
    entrenar_fn: Callable[..., dict[str, Any]] | None = None,
    **entrenar_kwargs: Any,
) -> dict[str, Any]:
    """Full-retrain degree-preserving permutation control (acceptance
    criterion 3): silhouette on the REAL gates must beat this control, not a
    reuse of cached real-graph gates -- so this function ALWAYS constructs a
    brand-new model over the permuted adjacency and performs a fresh
    training call; it never reads or returns any cached result.
    """
    if entrenar_fn is None:
        from chec_impacto.models.mgcecdl_graph import (
            entrenar_gated_autoencoder as entrenar_fn,  # type: ignore[assignment]
        )

    permuted_adjacency = control_permutacion_grados(A, seed=seed)
    permuted_edge_index = _edge_index_from_adjacency(permuted_adjacency, features)

    model = build_model_fn(permuted_adjacency, permuted_edge_index)
    loss_fn = build_loss_fn()

    result = dict(entrenar_fn(model, loss_fn, X_past, seed=seed, **entrenar_kwargs))
    result["permuted_adjacency"] = permuted_adjacency
    result["permuted_edge_index"] = permuted_edge_index
    return result


def seleccionar_k_datos(
    gate_means: np.ndarray,
    k_range: Sequence[int] = tuple(range(2, 11)),
    seeds: Sequence[int] = (0, 1, 2, 3, 4),
) -> dict[str, Any]:
    """Data-driven K sweep: silhouette + cross-seed ARI over `K` in `2..10`
    across `>=5` seeds.

    `k_raw` (the silhouette/ARI-selected K) is returned SEPARATELY from
    `tier_view` -- a 3-4 operational merge is a distinct, EXPLICIT,
    caller-driven step (it needs per-vano criticality to order clusters,
    ordinarily supplied downstream); `k_raw` is never silently overwritten
    or replaced by a forced tier count.
    """
    gate_means = np.asarray(gate_means, dtype=np.float64)
    n_vano = gate_means.shape[0]

    silhouette_by_k: dict[int, float] = {}
    ari_by_k: dict[int, float] = {}
    labels_by_k: dict[int, dict[int, np.ndarray]] = {}

    for k in k_range:
        if k >= n_vano:
            continue
        seed_to_labels: dict[int, np.ndarray] = {}
        seed_silhouettes: list[float] = []
        for seed in seeds:
            kmeans = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(gate_means)
            seed_to_labels[seed] = kmeans.labels_
            if len(set(kmeans.labels_)) > 1:
                seed_silhouettes.append(silhouette_score(gate_means, kmeans.labels_))

        labels_by_k[k] = seed_to_labels
        silhouette_by_k[k] = float(np.mean(seed_silhouettes)) if seed_silhouettes else float("nan")

        labels_list = list(seed_to_labels.values())
        pairwise_aris = [
            adjusted_rand_score(labels_list[i], labels_list[j])
            for i in range(len(labels_list))
            for j in range(i + 1, len(labels_list))
        ]
        ari_by_k[k] = float(np.mean(pairwise_aris)) if pairwise_aris else float("nan")

    valid_ks = [
        k for k in silhouette_by_k if np.isfinite(silhouette_by_k[k]) and np.isfinite(ari_by_k[k])
    ]
    if not valid_ks:
        raise ValueError("No valid K produced a defined silhouette/ARI over the requested range.")

    combined_score = {k: silhouette_by_k[k] + ari_by_k[k] for k in valid_ks}
    k_raw = max(valid_ks, key=lambda k: combined_score[k])
    reference_seed = seeds[0]

    return {
        "k_range": list(k_range),
        "silhouette_by_k": silhouette_by_k,
        "ari_by_k": ari_by_k,
        "labels_by_k": labels_by_k,
        "k_raw": k_raw,
        "labels_raw": labels_by_k[k_raw][reference_seed],
        # Never silently substituted for k_raw -- an explicit 3-4 tier merge, when
        # requested downstream, needs per-vano criticality to order clusters and is
        # therefore a distinct, separately-populated field.
        "tier_view": None,
    }


# ---------------------------------------------------------------------------
# Single-feature-proxy guard
# ---------------------------------------------------------------------------


def guardia_proxy_univariante(
    cluster_labels: np.ndarray,
    X: np.ndarray,
    features: Sequence[str],
    k: int,
    seed: int = 42,
    ari_threshold: float = 0.8,
) -> pd.DataFrame:
    """Single-feature-proxy guard (spec capability
    `criticality-evidence-protocol`, "UITI_VANO ablation and proxy guard").

    For EVERY feature, fits a 1-D `KMeans(k)` on that feature alone and
    scores ARI against `cluster_labels`; `max_f ARI > ari_threshold` VOIDS
    the result (`result.attrs["voided"]`). `UITI_VANO`, when present, is
    scored exactly like any other feature -- explicitly named in the
    returned table so a reader can find it directly.
    """
    X = np.asarray(X, dtype=np.float64)
    cluster_labels = np.asarray(cluster_labels)
    feature_list = list(features)
    if X.shape[1] != len(feature_list):
        raise ValueError("X column count must match len(features).")

    rows: list[dict[str, Any]] = []
    for index, name in enumerate(feature_list):
        column = X[:, index].reshape(-1, 1)
        kmeans = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(column)
        ari = adjusted_rand_score(cluster_labels, kmeans.labels_)
        rows.append({"feature": name, "ari": float(ari)})

    result = pd.DataFrame(rows).sort_values("ari", ascending=False).reset_index(drop=True)
    max_ari = float(result["ari"].max()) if not result.empty else 0.0
    result.attrs["max_ari"] = max_ari
    result.attrs["ari_threshold"] = ari_threshold
    result.attrs["voided"] = max_ari > ari_threshold
    if "UITI_VANO" in feature_list:
        result.attrs["uiti_vano_ari"] = float(
            result.loc[result["feature"] == "UITI_VANO", "ari"].iloc[0]
        )
    return result


# ---------------------------------------------------------------------------
# Future-window validation target + persistence diagnostic (D8)
# ---------------------------------------------------------------------------


def uiti_futuro_por_vano(
    df_original_copy: pd.DataFrame,
    future_mask: np.ndarray,
    target: str = "UITI_VANO",
) -> pd.DataFrame:
    """Per-vano accumulated FUTURE `target`, built STRICTLY from
    `future_mask` rows -- this is the validation target the model never
    sees during training (spec capability `criticality-evidence-protocol`,
    "Chronological p70 partition").
    """
    future_mask = np.asarray(future_mask, dtype=bool)
    if future_mask.shape[0] != len(df_original_copy):
        raise ValueError("future_mask length must match df_original_copy row count.")
    for column in ("CIRCUITO", "FID_VANO", target):
        if column not in df_original_copy.columns:
            raise ValueError(f"df_original_copy is missing required column {column!r}.")

    future_only = df_original_copy.loc[future_mask, ["CIRCUITO", "FID_VANO", target]]
    accumulated = (
        future_only.groupby(["CIRCUITO", "FID_VANO"], sort=False)
        .agg(
            **{
                f"{target}_futuro_acumulado": (target, "sum"),
                "n_eventos_futuro": (target, "size"),
            }
        )
        .reset_index()
    )
    return accumulated


def diagnostico_persistencia(
    df_original_copy: pd.DataFrame,
    past_mask: np.ndarray,
    future_mask: np.ndarray,
    target: str = "UITI_VANO",
) -> dict[str, Any]:
    """Three cheap discriminating tests for the negative past-vs-future
    persistence correlation (design D8) -- regression-to-the-mean, CHEC
    intervention (by `COD_CAUSA` family), and censoring -- run instead of
    speculating about which one explains it.
    """
    past_mask = np.asarray(past_mask, dtype=bool)
    future_mask = np.asarray(future_mask, dtype=bool)

    def _accumulate(mask: np.ndarray) -> pd.Series:
        subset = df_original_copy.loc[mask, ["CIRCUITO", "FID_VANO", target]]
        return subset.groupby(["CIRCUITO", "FID_VANO"], sort=False)[target].sum()

    past_totals = _accumulate(past_mask)
    future_totals = _accumulate(future_mask)

    both_windows = past_totals.to_frame("past").join(future_totals.to_frame("future"), how="inner")
    primary_correlation = (
        float(both_windows["past"].corr(both_windows["future"], method="spearman"))
        if len(both_windows) > 1
        else float("nan")
    )

    # 1. Regression to the mean / noise: recompute the SAME Spearman WITHIN the
    #    past window (past-early vs past-late halves, split on FECHA's median).
    rtm_correlation = float("nan")
    past_df = df_original_copy.loc[past_mask]
    if "FECHA" in past_df.columns and not past_df.empty:
        median_fecha = past_df["FECHA"].median()
        early_mask = (past_df["FECHA"] <= median_fecha).to_numpy()
        early_totals = (
            past_df.loc[early_mask].groupby(["CIRCUITO", "FID_VANO"], sort=False)[target].sum()
        )
        late_totals = (
            past_df.loc[~early_mask].groupby(["CIRCUITO", "FID_VANO"], sort=False)[target].sum()
        )
        rtm_both = early_totals.to_frame("early").join(late_totals.to_frame("late"), how="inner")
        if len(rtm_both) > 1:
            rtm_correlation = float(rtm_both["early"].corr(rtm_both["late"], method="spearman"))

    # 2. CHEC intervention: split the drop by COD_CAUSA family -- a concentrated
    #    drop in actionable causes reads as intervention, a diffuse one does not.
    intervention_rows: list[dict[str, Any]] = []
    if "COD_CAUSA" in df_original_copy.columns:
        past_by_cause = df_original_copy.loc[past_mask].groupby("COD_CAUSA")[target].sum()
        future_by_cause = df_original_copy.loc[future_mask].groupby("COD_CAUSA")[target].sum()
        causes = sorted(set(past_by_cause.index) | set(future_by_cause.index))
        for cause in causes:
            past_value = float(past_by_cause.get(cause, 0.0))
            future_value = float(future_by_cause.get(cause, 0.0))
            intervention_rows.append(
                {
                    "COD_CAUSA": cause,
                    "past_total": past_value,
                    "future_total": future_value,
                    "delta": future_value - past_value,
                }
            )
    intervention_by_cod_causa = pd.DataFrame(intervention_rows)

    # 3. Censoring: recompute on ALL vanos with future presence (past count 0 for
    #    absentees), unrestricted by the both-windows requirement -- a sign flip
    #    versus the primary correlation reads as a censoring artifact.
    censoring_correlation = float("nan")
    n_vanos_unrestricted = 0
    if len(future_totals) > 0:
        past_reindexed = past_totals.reindex(future_totals.index, fill_value=0.0)
        censoring_both = past_reindexed.to_frame("past").join(future_totals.to_frame("future"))
        n_vanos_unrestricted = int(len(censoring_both))
        if n_vanos_unrestricted > 1:
            censoring_correlation = float(
                censoring_both["past"].corr(censoring_both["future"], method="spearman")
            )

    return {
        "primary_correlation_both_windows": primary_correlation,
        "n_vanos_both_windows": int(len(both_windows)),
        "regression_to_mean_correlation": rtm_correlation,
        "intervention_by_cod_causa": intervention_by_cod_causa,
        "censoring_correlation_unrestricted": censoring_correlation,
        "n_vanos_unrestricted": n_vanos_unrestricted,
    }


def corregir_benjamini_hochberg(p_values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg step-up adjustment, returned in the INPUT order.

    Implemented here rather than pulled from `statsmodels` because it is a
    dozen lines and the repository has no other use for that dependency.
    """
    raw = np.asarray(p_values, dtype=float).reshape(-1)
    if raw.size == 0:
        return raw.copy()
    if np.any((raw < 0.0) | (raw > 1.0)):
        raise ValueError("p_values must lie in [0, 1].")

    n_tests = raw.size
    ascending = np.argsort(raw)
    ranked = raw[ascending]
    # Walk from the largest p-value down, keeping the running minimum of
    # (m / rank) * p -- this is what makes the result monotone.
    scaled_descending = (n_tests / np.arange(n_tests, 0, -1)) * ranked[::-1]
    adjusted_ascending = np.minimum.accumulate(scaled_descending)[::-1]

    adjusted = np.empty_like(adjusted_ascending)
    adjusted[ascending] = np.clip(adjusted_ascending, 0.0, 1.0)
    return adjusted


def asociacion_criticidad(
    cluster_labels: Sequence[int] | np.ndarray,
    values: Sequence[float] | np.ndarray,
) -> dict[str, Any]:
    """Test whether per-vano `values` (the FUTURE accumulated criticality
    target) differ across clusters, without assuming normality.

    Returns the Kruskal-Wallis `H`/`p_value`, the `epsilon_squared` effect
    size, and a `pairwise` frame of Dunn post-hoc comparisons carrying both
    raw and Benjamini-Hochberg-adjusted p-values.

    A significant `p_value` on its own says only that SOME cluster differs;
    `epsilon_squared` is what says whether the difference is large enough to
    act on, which is why both are always reported together.
    """
    labels = np.asarray(cluster_labels).reshape(-1)
    observations = np.asarray(values, dtype=float).reshape(-1)
    if labels.size != observations.size:
        raise ValueError("cluster_labels and values must have the same length.")

    clusters = np.unique(labels)
    n_clusters = clusters.size
    if n_clusters < 2:
        raise ValueError("asociacion_criticidad needs at least two clusters to compare.")

    n_total = observations.size
    groups = [observations[labels == cluster] for cluster in clusters]
    h_statistic, p_value = kruskal(*groups)

    # Tomczak & Tomczak (2014): eps^2 = H / ((n^2 - 1)/(n + 1)) = H / (n - 1).
    epsilon_squared = float(h_statistic) / (n_total - 1)

    # Dunn post-hoc over the POOLED mid-ranks, with the standard tie
    # correction. For exactly two clusters this construction satisfies
    # z^2 == H, which the test suite pins as a correctness anchor.
    pooled_ranks = rankdata(observations)
    mean_rank = {c: float(pooled_ranks[labels == c].mean()) for c in clusters}
    group_size = {c: int(np.count_nonzero(labels == c)) for c in clusters}

    _, tie_counts = np.unique(observations, return_counts=True)
    tied = tie_counts[tie_counts > 1].astype(float)
    tie_term = float(np.sum(tied**3 - tied))
    rank_variance = (n_total * (n_total + 1)) / 12.0 - tie_term / (12.0 * (n_total - 1))

    comparisons: list[dict[str, Any]] = []
    for index, cluster_a in enumerate(clusters):
        for cluster_b in clusters[index + 1 :]:
            standard_error = np.sqrt(
                rank_variance * (1.0 / group_size[cluster_a] + 1.0 / group_size[cluster_b])
            )
            z_score = (mean_rank[cluster_a] - mean_rank[cluster_b]) / standard_error
            comparisons.append(
                {
                    "cluster_a": cluster_a,
                    "cluster_b": cluster_b,
                    "n_a": group_size[cluster_a],
                    "n_b": group_size[cluster_b],
                    "mean_rank_a": mean_rank[cluster_a],
                    "mean_rank_b": mean_rank[cluster_b],
                    "z": float(z_score),
                    "p_value": float(2.0 * norm.sf(abs(z_score))),
                }
            )

    pairwise = pd.DataFrame(comparisons)
    pairwise["p_value_bh"] = corregir_benjamini_hochberg(pairwise["p_value"].to_numpy())

    return {
        "H": float(h_statistic),
        "p_value": float(p_value),
        "epsilon_squared": epsilon_squared,
        "n": int(n_total),
        "k": int(n_clusters),
        "pairwise": pairwise,
    }
