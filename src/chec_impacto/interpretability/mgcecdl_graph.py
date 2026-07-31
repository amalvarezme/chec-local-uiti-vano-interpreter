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

PR4 adds the CHARACTERIZATION protocol (notebook 12 pivots from a predictive
to a descriptive/taxonomic question): the Ben-Hur-style cluster-stability
protocol (`estabilidad_por_submuestreo`), out-of-fold classifier
separability with feature importances (`separabilidad_fuera_de_pliegue`),
and the per-cluster standardized-effect profile (`perfil_por_cluster`).

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

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.model_selection import StratifiedKFold

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


# ---------------------------------------------------------------------------
# PR4 -- characterization protocol: cluster stability, out-of-fold
# separability, and per-cluster standardized-effect profiles.
#
# These answer "is this partition real structure or a fitting artifact?"
# (`estabilidad_por_submuestreo`), "does a classifier recover the partition
# out of fold, and on what does it rely?" (`separabilidad_fuera_de_pliegue`),
# and "how does a family differ from the population, per dimension?"
# (`perfil_por_cluster`). See sdd/notebook-12-criticality-representation
# apply-progress (PR4) and the decision that redirects notebook 12 from
# PREDICTION to CHARACTERIZATION.
# ---------------------------------------------------------------------------


def _ari_sobre_filas_compartidas(
    idx_a: np.ndarray,
    labels_a: np.ndarray,
    idx_b: np.ndarray,
    labels_b: np.ndarray,
) -> tuple[float, int]:
    """ARI between `labels_a`/`labels_b` restricted to the GLOBAL row indices
    present in BOTH `idx_a` and `idx_b`, aligned by identity (never by
    within-subsample position). Returns `(ari, n_shared)`.
    """
    idx_a = np.asarray(idx_a)
    idx_b = np.asarray(idx_b)
    labels_a = np.asarray(labels_a)
    labels_b = np.asarray(labels_b)

    shared = np.intersect1d(idx_a, idx_b)
    if shared.size == 0:
        return float("nan"), 0

    position_in_a = {global_index: position for position, global_index in enumerate(idx_a)}
    position_in_b = {global_index: position for position, global_index in enumerate(idx_b)}
    aligned_labels_a = np.array([labels_a[position_in_a[g]] for g in shared])
    aligned_labels_b = np.array([labels_b[position_in_b[g]] for g in shared])

    return float(adjusted_rand_score(aligned_labels_a, aligned_labels_b)), int(shared.size)


def estabilidad_por_submuestreo(
    values: np.ndarray,
    k_values: Sequence[int],
    n_repeticiones: int = 10,
    fraccion: float = 0.8,
    seed: int = 42,
) -> dict[str, Any]:
    """Ben-Hur-style cluster-stability protocol.

    For each `K` in `k_values` and each of `n_repeticiones` repetitions, draw
    TWO independent overlapping subsamples of `fraccion` of the rows, cluster
    each subsample INDEPENDENTLY with `KMeans(K)`, and compute the ARI over
    ONLY the vanos present in both subsamples (`_ari_sobre_filas_compartidas`
    -- aligned by global row identity, never by within-subsample position).

    This is the operational meaning of "the partition is consistent": a
    partition that is a fitting artifact does not reproduce across
    independent subsamples of the same data, so its cross-subsample ARI
    collapses toward 0; real structure reproduces, so its ARI stays high.

    Returns `k_values`, `mean_ari_by_k`, `std_ari_by_k` (per-K mean/std over
    repetitions), and `raw_ari_by_k` (the per-repetition values).
    """
    values = np.asarray(values, dtype=np.float64)
    n_rows = values.shape[0]
    n_sub = max(int(round(fraccion * n_rows)), 2)
    rng = np.random.default_rng(seed)

    k_values = list(k_values)
    mean_ari_by_k: dict[int, float] = {}
    std_ari_by_k: dict[int, float] = {}
    raw_ari_by_k: dict[int, list[float]] = {}

    for k in k_values:
        repetition_aris: list[float] = []
        for repetition_index in range(n_repeticiones):
            idx_a = rng.choice(n_rows, size=n_sub, replace=False)
            idx_b = rng.choice(n_rows, size=n_sub, replace=False)

            kmeans_seed = seed + 1000 * (k + 1) + repetition_index
            labels_a = (
                KMeans(n_clusters=k, n_init=10, random_state=kmeans_seed).fit(values[idx_a]).labels_
            )
            labels_b = (
                KMeans(n_clusters=k, n_init=10, random_state=kmeans_seed).fit(values[idx_b]).labels_
            )

            ari, n_shared = _ari_sobre_filas_compartidas(idx_a, labels_a, idx_b, labels_b)
            repetition_aris.append(ari if n_shared >= 2 else float("nan"))

        raw_ari_by_k[k] = repetition_aris
        valid_aris = [value for value in repetition_aris if np.isfinite(value)]
        mean_ari_by_k[k] = float(np.mean(valid_aris)) if valid_aris else float("nan")
        std_ari_by_k[k] = float(np.std(valid_aris)) if valid_aris else float("nan")

    return {
        "k_values": k_values,
        "mean_ari_by_k": mean_ari_by_k,
        "std_ari_by_k": std_ari_by_k,
        "raw_ari_by_k": raw_ari_by_k,
    }


def separabilidad_fuera_de_pliegue(
    features: np.ndarray,
    labels: np.ndarray,
    n_splits: int = 5,
    seed: int = 42,
    feature_names: Sequence[str] | None = None,
    n_estimators: int = 200,
) -> dict[str, Any]:
    """Out-of-fold classifier separability of a cluster partition.

    `StratifiedKFold(n_splits)` over `labels` with a fresh
    `RandomForestClassifier` per fold -- its feature importances are the
    interpretability payload, since every dimension is a NAMED expert edge
    when this is called on the gate means. Returns out-of-fold BALANCED
    accuracy (never raw accuracy -- clusters are usually imbalanced, and raw
    accuracy silently rewards predicting the majority cluster), the per-fold
    values, the confusion matrix, and feature importances ranked descending
    (mean across folds, each fold's importances already sum to 1, so the
    mean does too).
    """
    X = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels)
    if X.shape[0] != y.shape[0]:
        raise ValueError("features and labels must have the same number of rows.")

    n_features = X.shape[1]
    names = list(feature_names) if feature_names is not None else [f"dim_{i}" for i in range(n_features)]
    if len(names) != n_features:
        raise ValueError("feature_names length must match features' column count.")

    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    out_of_fold_predictions = np.empty_like(y)
    fold_balanced_accuracies: list[float] = []
    importances_per_fold: list[np.ndarray] = []

    for fold_index, (train_index, test_index) in enumerate(splitter.split(X, y)):
        classifier = RandomForestClassifier(n_estimators=n_estimators, random_state=seed + fold_index)
        classifier.fit(X[train_index], y[train_index])
        fold_predictions = classifier.predict(X[test_index])
        out_of_fold_predictions[test_index] = fold_predictions
        fold_balanced_accuracies.append(
            float(balanced_accuracy_score(y[test_index], fold_predictions))
        )
        importances_per_fold.append(classifier.feature_importances_)

    overall_balanced_accuracy = float(balanced_accuracy_score(y, out_of_fold_predictions))
    mean_importances = np.mean(importances_per_fold, axis=0)
    descending_order = np.argsort(mean_importances)[::-1]
    feature_importances = pd.DataFrame(
        {
            "feature": [names[i] for i in descending_order],
            "importance": mean_importances[descending_order],
        }
    )

    return {
        "balanced_accuracy": overall_balanced_accuracy,
        "balanced_accuracy_by_fold": fold_balanced_accuracies,
        "confusion_matrix": confusion_matrix(y, out_of_fold_predictions, labels=np.unique(y)),
        "feature_importances": feature_importances,
        "out_of_fold_predictions": out_of_fold_predictions,
        "n_splits": n_splits,
    }


def perfil_por_cluster(
    values: np.ndarray,
    nombres: Sequence[str],
    labels: np.ndarray,
) -> pd.DataFrame:
    """Per-cluster vs population profile with standardized effect size.

    `efecto_estandarizado = (media_cluster - media_poblacion) / desv_poblacion`
    per dimension, ranked by descending absolute effect WITHIN each cluster.
    A population standard deviation of (near) zero would make that ratio
    `inf`/`nan`; such a dimension carries no discriminating information by
    construction (every value is identical), so its effect is reported as
    exactly `0.0` instead of a silently propagated `inf`/`nan`.

    Returns a tidy DataFrame: `cluster | nombre | media_cluster |
    media_poblacion | efecto_estandarizado | rank`.
    """
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError(f"values must be 2-D (n_samples, n_dims); got shape {values.shape}.")
    names = list(nombres)
    if values.shape[1] != len(names):
        raise ValueError("values column count must match len(nombres).")
    labels = np.asarray(labels)
    if labels.shape[0] != values.shape[0]:
        raise ValueError("labels must have the same length as values' first axis.")

    population_mean = values.mean(axis=0)
    population_std = values.std(axis=0, ddof=0)
    _ZERO_STD_THRESHOLD = 1e-12

    rows: list[dict[str, Any]] = []
    for cluster in sorted(np.unique(labels)):
        cluster_mean = values[labels == cluster].mean(axis=0)
        for dim_index, name in enumerate(names):
            std = population_std[dim_index]
            if not np.isfinite(std) or std < _ZERO_STD_THRESHOLD:
                effect = 0.0
            else:
                effect = float((cluster_mean[dim_index] - population_mean[dim_index]) / std)
            rows.append(
                {
                    "cluster": cluster,
                    "nombre": name,
                    "media_cluster": float(cluster_mean[dim_index]),
                    "media_poblacion": float(population_mean[dim_index]),
                    "efecto_estandarizado": effect,
                }
            )

    result = pd.DataFrame(rows)
    result["rank"] = (
        result.groupby("cluster")["efecto_estandarizado"]
        .transform(lambda column: column.abs().rank(ascending=False, method="first"))
        .astype(int)
    )
    return result.sort_values(["cluster", "rank"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# PR4 (cont.) -- the per-group RECONSTRUCTED graph and the descriptive
# vocabulary built on top of it: graph-vs-graph affinity, UITI-ordered risk
# naming, and fine-vs-coarse partition nesting.
# ---------------------------------------------------------------------------


def grafo_reconstruido_por_grupo(
    gate_means: np.ndarray,
    edge_index: GraphEdgeIndex,
    labels: np.ndarray,
    n_features: int,
) -> dict[int, dict]:
    """Rebuild each group's mean expert graph from its per-vano edge gates.

    A group's reconstructed edge weight is `mean_vano(g_bar_e) *
    fixed_weight_e` -- the fixed expert graph as that family of vanos
    actually uses it. Returns, per group in ASCENDING label order,
    `{"gate_mean", "edge_weights", "matrix", "n_vanos"}`.

    `matrix` is a dense `(n_features, n_features)` array filled STRICTLY
    through `edge_index.pairs`; edge `i` never goes anywhere its
    `(source_position, target_position)` pair does not say, so the result
    stays correct regardless of the order `edge_index` happens to be in.
    Every cell outside the edge index's support stays exactly zero.
    """
    gate_means = np.asarray(gate_means, dtype=np.float64)
    if gate_means.ndim != 2:
        raise ValueError(
            f"gate_means must be 2-D (n_vanos, n_edges); got shape {gate_means.shape}."
        )

    labels = np.asarray(labels).reshape(-1)
    if labels.shape[0] != gate_means.shape[0]:
        raise ValueError(
            f"labels has {labels.shape[0]} entries but gate_means has "
            f"{gate_means.shape[0]} rows (vanos); they must match."
        )
    if gate_means.shape[1] != edge_index.n_edges:
        raise ValueError(
            f"gate_means has {gate_means.shape[1]} columns but edge_index.n_edges is "
            f"{edge_index.n_edges}; they must match."
        )

    pairs = np.asarray(edge_index.pairs, dtype=np.int64)
    max_position = int(pairs.max())
    n_features = int(n_features)
    if n_features <= max_position:
        raise ValueError(
            f"n_features ({n_features}) cannot hold edge_index's maximum feature position "
            f"({max_position}); it must be at least {max_position + 1}."
        )

    fixed_weights = np.asarray(edge_index.weights, dtype=np.float64)

    reconstruido: dict[int, dict] = {}
    for group in sorted(np.unique(labels)):
        group_mask = labels == group
        gate_mean = gate_means[group_mask].mean(axis=0)
        edge_weights = gate_mean * fixed_weights

        matrix = np.zeros((n_features, n_features), dtype=np.float64)
        matrix[pairs[:, 0], pairs[:, 1]] = edge_weights

        reconstruido[_como_escalar_python(group)] = {
            "gate_mean": gate_mean,
            "edge_weights": edge_weights,
            "matrix": matrix,
            "n_vanos": int(np.count_nonzero(group_mask)),
        }
    return reconstruido


_METRICAS_AFINIDAD = ("coseno", "correlacion")


def afinidad_entre_grafos(
    edge_weights_por_grupo: Mapping[int, np.ndarray],
    edge_weights_fijo: np.ndarray,
    metrica: str = "coseno",
) -> pd.DataFrame:
    """Square symmetric affinity between every reconstructed graph and the
    fixed expert graph, indexed `["FIJO", *sorted(groups)]` (labels
    stringified). `frame.attrs["metrica"]` records which metric was used.

    Which metric, and why it matters:

    - `"coseno"` -- plain cosine similarity over the `E` edge weights. Read
      it with care: every reconstructed graph is `gate * fixed_weight` with
      gates centred near 1, so a cosine of 0.999 against `FIJO` (or against
      another group) is what this construction produces BY DEFAULT. It says
      "these vectors share the expert graph's magnitude profile", which they
      cannot help but do. It does NOT say the groups are identical, and a
      reader who treats a high cosine as evidence of agreement is reading a
      property of the parameterization, not a property of the data.
    - `"correlacion"` -- Pearson over the same `E` edges. Centring each
      vector removes the shared offset that pins cosine near 1, leaving only
      the per-edge DEVIATION pattern. Two groups that gate the same edges in
      opposite directions land at a negative correlation while their cosine
      still reads ~1.0, which is exactly the discriminating power the caller
      needs. Its own caveat: when the fixed weights themselves vary widely,
      that shared ramp survives centring and correlation saturates too --
      neither metric is a substitute for the per-edge deviation table.

    Any other `metrica` raises `ValueError`. The diagonal is exactly `1.0`.
    """
    if metrica not in _METRICAS_AFINIDAD:
        raise ValueError(
            f"metrica must be one of {_METRICAS_AFINIDAD}; got {metrica!r}."
        )

    fijo = np.asarray(edge_weights_fijo, dtype=np.float64).reshape(-1)
    etiquetas = ["FIJO"]
    vectores = [fijo]
    for group in sorted(edge_weights_por_grupo):
        vector = np.asarray(edge_weights_por_grupo[group], dtype=np.float64).reshape(-1)
        if vector.shape != fijo.shape:
            raise ValueError(
                f"group {group!r} has {vector.shape[0]} edge weights but edge_weights_fijo "
                f"has {fijo.shape[0]}; every graph must span the same edge set."
            )
        etiquetas.append(str(group))
        vectores.append(vector)

    matriz = np.vstack(vectores)
    if metrica == "correlacion":
        # Pearson IS cosine on the centred vectors -- centring is the only
        # difference, so both metrics share one code path from here on.
        matriz = matriz - matriz.mean(axis=1, keepdims=True)

    norms = np.linalg.norm(matriz, axis=1)
    # A zero-norm row (a constant graph under "correlacion") has no direction:
    # its off-diagonal affinity is undefined, reported as 0.0 rather than nan.
    normalizada = np.zeros_like(matriz)
    nonzero = norms > 0.0
    normalizada[nonzero] = matriz[nonzero] / norms[nonzero, None]

    afinidad = np.clip(normalizada @ normalizada.T, -1.0, 1.0)
    np.fill_diagonal(afinidad, 1.0)

    frame = pd.DataFrame(afinidad, index=etiquetas, columns=etiquetas)
    frame.attrs["metrica"] = metrica
    return frame


def _como_escalar_python(value: Any) -> Any:
    """Numpy scalars out of `np.unique` become plain Python scalars, so the
    returned dict keys compare and print like the caller's own labels."""
    return value.item() if hasattr(value, "item") else value


def asignar_nombres_de_riesgo(
    labels: np.ndarray,
    valores: np.ndarray,
    nombres: Sequence[str] = ("Bajo", "Medio", "Medio-Alto", "Alto"),
) -> dict:
    """Re-label groups by ASCENDING group-mean `valores` (per-vano accumulated
    UITI), so group `0` is always the lowest-criticality family.

    KMeans label ids are arbitrary: cluster `0` carries no ordinal meaning at
    all. This function replaces them with an ORDERED vocabulary, which is what
    lets a downstream reader treat "Alto" as a claim about criticality rather
    than about an arbitrary centroid index.

    Returns `{"labels", "mapeo", "nombres", "resumen"}`, where `resumen` is
    one row per NEW group -- `grupo | nombre | n_vanos | uiti_media |
    uiti_mediana` -- sorted by `grupo`.

    `valores` may hold NaN (a vano with no events in the future window).
    Group statistics are NaN-aware; a group that is ENTIRELY NaN has no
    measurable criticality, so it sorts to the bottom (as if `-inf`) instead
    of crashing, and its `uiti_media`/`uiti_mediana` stay NaN in `resumen`
    rather than being silently reported as a real number.

    Fewer groups than `nombres` is fine (the first `n` names are used); MORE
    groups than names raises, because there is no honest name left to give.
    """
    labels = np.asarray(labels).reshape(-1)
    valores = np.asarray(valores, dtype=np.float64).reshape(-1)
    if labels.shape[0] != valores.shape[0]:
        raise ValueError(
            f"labels has {labels.shape[0]} entries but valores has {valores.shape[0]}; "
            "they must be per-vano aligned."
        )

    nombres_disponibles = [str(name) for name in nombres]
    etiquetas_originales = list(np.unique(labels))
    if len(etiquetas_originales) > len(nombres_disponibles):
        raise ValueError(
            f"{len(etiquetas_originales)} distinct labels do not fit the "
            f"{len(nombres_disponibles)} available nombres {tuple(nombres_disponibles)}; "
            "supply a longer `nombres` sequence."
        )

    def _estadisticos(original: Any) -> tuple[np.ndarray, bool]:
        group_values = valores[labels == original]
        todo_nan = group_values.size == 0 or bool(np.all(np.isnan(group_values)))
        return group_values, todo_nan

    claves_de_orden: list[float] = []
    for original in etiquetas_originales:
        group_values, todo_nan = _estadisticos(original)
        claves_de_orden.append(
            float("-inf") if todo_nan else float(np.nanmean(group_values))
        )

    orden_ascendente = np.argsort(np.asarray(claves_de_orden), kind="stable")
    mapeo: dict[Any, int] = {}
    original_por_nuevo: list[Any] = []
    for nuevo_label, position in enumerate(orden_ascendente):
        original = etiquetas_originales[int(position)]
        mapeo[_como_escalar_python(original)] = nuevo_label
        original_por_nuevo.append(original)

    labels_remapeados = np.array(
        [mapeo[_como_escalar_python(value)] for value in labels], dtype=int
    )
    nombres_por_grupo = {
        nuevo_label: nombres_disponibles[nuevo_label]
        for nuevo_label in range(len(etiquetas_originales))
    }

    filas: list[dict[str, Any]] = []
    for nuevo_label, original in enumerate(original_por_nuevo):
        group_values, todo_nan = _estadisticos(original)
        filas.append(
            {
                "grupo": nuevo_label,
                "nombre": nombres_por_grupo[nuevo_label],
                "n_vanos": int(group_values.size),
                "uiti_media": float("nan") if todo_nan else float(np.nanmean(group_values)),
                "uiti_mediana": (
                    float("nan") if todo_nan else float(np.nanmedian(group_values))
                ),
            }
        )

    resumen = pd.DataFrame(
        filas, columns=["grupo", "nombre", "n_vanos", "uiti_media", "uiti_mediana"]
    ).sort_values("grupo").reset_index(drop=True)

    return {
        "labels": labels_remapeados,
        "mapeo": mapeo,
        "nombres": nombres_por_grupo,
        "resumen": resumen,
    }


def anidamiento_entre_particiones(
    labels_finas: np.ndarray,
    labels_gruesas: np.ndarray,
    umbral_pureza: float = 0.99,
) -> pd.DataFrame:
    """Does the FINE partition nest inside the coarse one? Reported PER FINE
    FAMILY, never as one global boolean.

    One row per fine family: `familia_fina | n_vanos |
    familia_gruesa_dominante | pureza | anida`, where `pureza` is the
    fraction of that family sitting in its dominant coarse family and `anida`
    is `pureza >= umbral_pureza`.

    `frame.attrs` carries `"contingencia"` (the fine-by-coarse crosstab),
    `"pureza_minima"`, `"pureza_media"`, `"ari"` (adjusted Rand index) and
    `"fraccion_vanos_anidados"` -- the share of ALL vanos living in families
    that nest.

    Why there is deliberately NO overall verdict: an earlier version of this
    analysis collapsed the answer into a single boolean driven by MINIMUM
    purity, and reported a flat "does not nest" for a real case where three
    of four families were 100% pure and one small family (4% of the vanos)
    straddled the boundary. That boolean erased the actual finding.
    `pureza_minima` and `fraccion_vanos_anidados` are BOTH reported here
    precisely because they can tell different stories (0.5 and 0.96 in that
    case), and describing the resulting structure is the caller's job.
    """
    finas = np.asarray(labels_finas).reshape(-1)
    gruesas = np.asarray(labels_gruesas).reshape(-1)
    if finas.shape[0] != gruesas.shape[0]:
        raise ValueError(
            f"labels_finas has {finas.shape[0]} entries but labels_gruesas has "
            f"{gruesas.shape[0]}; both must be per-vano aligned."
        )
    if finas.shape[0] == 0:
        raise ValueError("anidamiento_entre_particiones needs at least one vano.")

    contingencia = pd.crosstab(
        pd.Series(finas, name="familia_fina"),
        pd.Series(gruesas, name="familia_gruesa"),
    )

    filas: list[dict[str, Any]] = []
    for familia_fina, conteos in contingencia.iterrows():
        n_vanos = int(conteos.sum())
        dominante = conteos.idxmax()
        pureza = float(conteos.max()) / n_vanos
        filas.append(
            {
                "familia_fina": _como_escalar_python(familia_fina),
                "n_vanos": n_vanos,
                "familia_gruesa_dominante": _como_escalar_python(dominante),
                "pureza": pureza,
                "anida": bool(pureza >= umbral_pureza),
            }
        )

    frame = pd.DataFrame(
        filas,
        columns=[
            "familia_fina",
            "n_vanos",
            "familia_gruesa_dominante",
            "pureza",
            "anida",
        ],
    )

    n_total = int(finas.shape[0])
    n_anidados = int(frame.loc[frame["anida"], "n_vanos"].sum())
    frame.attrs["contingencia"] = contingencia
    frame.attrs["pureza_minima"] = float(frame["pureza"].min())
    frame.attrs["pureza_media"] = float(frame["pureza"].mean())
    frame.attrs["ari"] = float(adjusted_rand_score(finas, gruesas))
    frame.attrs["fraccion_vanos_anidados"] = n_anidados / n_total
    return frame
