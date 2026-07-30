"""Optuna search objective for the per-sample edge-gate autoencoder
(`chec_impacto.models.mgcecdl_graph`).

Maximizes mean pairwise cross-seed ARI of the vano clustering, subject to a
reconstruction-loss feasibility bound `tau` -- reconstruction-alone,
silhouette-alone, and any criterion touching a chronologically LATER,
held-out `UITI_VANO` validation window are all deliberately excluded (spec
capability `graph-regime-clustering`).

Search-time SEEDS here are `{0,1,2}`, quarantined from the acceptance gate's
disjoint `{10..14}` seed set (design D3) -- both are caller-supplied, this
module never invents its own default seed set that could accidentally
collide with the gate's. `k_search` is likewise a SEARCH-TIME constant only:
the objective always returns a bare ARI float, never a "K", so it can never
leak out as "the" reported cluster count.

This module never reads any held-out validation-window value -- confirmed
by a dedicated grep-guard test on this exact file.

Placed under `src/chec_impacto/models/` (not `src/chec_impacto/training/`,
edit-denied) following the same precedent as `mgcecdl_graph.py` (D6).

Implementation note: `chec_impacto.interpretability.mgcecdl_graph` itself
imports `chec_impacto.models.mgcecdl_graph` at its top level (for the
`GraphEdgeIndex` type), and `chec_impacto.models.__init__` imports THIS
module -- a top-level `from chec_impacto.interpretability.mgcecdl_graph
import ...` here would therefore be circular. The one place that needs
`agrupar_gates_por_vano` (`_default_extraer_gate_means_fn`) imports it
lazily instead, the same deferred-import pattern used throughout
`mgcecdl_graph.py`/`mgcecdl.py` for the models<->training boundary.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import optuna
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score

_DEGENERATE_PARTITION_SENTINEL = -1.0
_MIN_MINORITY_CLUSTER_FRACTION = 0.01

# Carried fixed hyperparameters (notebook-11-validated pruning, design's
# "Optuna objective (implementation)"): `sgd` excluded, everything else here
# is swept.
OPTIMIZER_CHOICES = ("adam", "adamw")
LAMBDA_MI_CHOICES = (0.01, 0.1, 0.3, 1.0)
# `lambda_dev` sweep INCLUDES 0.0 so a null gate-variance result can never be
# blamed on the regularizer alone (spec requirement).
LAMBDA_DEV_CHOICES = (0.0, 1e-3, 1e-2, 1e-1)


def mean_pairwise_ari(labels_by_seed: Sequence[np.ndarray]) -> float:
    """Mean pairwise Adjusted Rand Index across a set of per-seed cluster
    label arrays. `nan` when fewer than two label arrays are supplied."""
    pairwise_scores = [
        adjusted_rand_score(labels_by_seed[i], labels_by_seed[j])
        for i in range(len(labels_by_seed))
        for j in range(i + 1, len(labels_by_seed))
    ]
    return float(np.mean(pairwise_scores)) if pairwise_scores else float("nan")


def _default_build_model_fn(meta: Mapping[str, Any], params: Mapping[str, Any]) -> Any:
    from chec_impacto.models.mgcecdl import MGCECDLRegressor
    from chec_impacto.models.mgcecdl_graph import GraphGatedMGCECDLRegressor

    base = MGCECDLRegressor(
        modality_feature_indices=meta["modality_feature_indices"],
        hidden_dim=meta.get("hidden_dim", 64),
        embed_dim=meta.get("embed_dim", 96),
        dropout=params["dropout"],
    )
    return GraphGatedMGCECDLRegressor(
        base=base,
        adjacency=meta["adjacency"],
        edge_index=meta["edge_index"],
        alpha=params["alpha"],
    )


def _default_build_loss_fn(meta: Mapping[str, Any], params: Mapping[str, Any]) -> Any:
    from chec_impacto.models.mgcecdl_graph import GatedSelfSupervisedLoss

    return GatedSelfSupervisedLoss(
        feature_mean=meta["feature_mean"],
        feature_std=meta["feature_std"],
        adjacency_matrix=meta["adjacency"],
        lambda_reconstruction=params["lambda_reconstruction"],
        lambda_mutual_information=params["lambda_mutual_information"],
        lambda_gate_deviation=params["lambda_gate_deviation"],
        reconstruction_normalization="soft",
    )


def _default_entrenar_fn(model: Any, loss_fn: Any, X_past: np.ndarray, **kwargs: Any) -> dict[str, Any]:
    from chec_impacto.models.mgcecdl_graph import entrenar_gated_autoencoder

    return entrenar_gated_autoencoder(model, loss_fn, X_past, **kwargs)


def _default_extraer_gate_means_fn(
    entrenar_result: Mapping[str, Any],
    meta: Mapping[str, Any],
    X_past: np.ndarray,
) -> np.ndarray:
    import torch

    from chec_impacto.interpretability.mgcecdl_graph import agrupar_gates_por_vano

    model = entrenar_result["model"]
    model.eval()
    with torch.no_grad():
        X_tensor = torch.as_tensor(np.asarray(X_past), dtype=torch.float32)
        output = model(X_tensor)
    gates = output["edge_gates"].cpu().numpy()
    gate_means, _ = agrupar_gates_por_vano(gates, meta["circuito"], meta["fid_vano"])
    return gate_means


def construir_objetivo_gated(
    X_past: np.ndarray,
    meta: Mapping[str, Any],
    tau: float,
    *,
    seeds: Sequence[int] = (0, 1, 2),
    k_search: int = 4,
    epochs: int,
    entrenar_fn: Callable[..., dict[str, Any]] | None = None,
    build_model_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None = None,
    build_loss_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None = None,
    extraer_gate_means_fn: Callable[[Mapping[str, Any]], np.ndarray] | None = None,
) -> Callable[["optuna.trial.Trial"], float]:
    """Build the Optuna objective (design's "Optuna objective
    (implementation)"): maximize mean pairwise cross-seed ARI of the vano
    clustering, subject to `reconstruction_loss_raw <= tau`.

    `seeds` MUST be the search-time seed set -- disjoint from whatever seed
    set the acceptance gate re-runs on afterwards (design D3); this function
    performs no seed bookkeeping of its own beyond training on exactly the
    seeds it is given, in order, once each.

    `entrenar_fn`/`build_model_fn`/`build_loss_fn`/`extraer_gate_means_fn`
    default to real construction via `chec_impacto.models.mgcecdl`/
    `mgcecdl_graph` (imported lazily so this module stays cheap to import),
    but tests inject stubs -- the acceptance runtime harness for this unit
    is a 2-trial stub study, never a real training run.
    """
    entrenar_fn = entrenar_fn or _default_entrenar_fn
    build_model_fn = build_model_fn or _default_build_model_fn
    build_loss_fn = build_loss_fn or _default_build_loss_fn
    if extraer_gate_means_fn is None:
        def extraer_gate_means_fn(entrenar_result: Mapping[str, Any]) -> np.ndarray:
            return _default_extraer_gate_means_fn(entrenar_result, meta, X_past)

    def objective(trial: "optuna.trial.Trial") -> float:
        params = {
            "lr": trial.suggest_float("lr", 1e-4, 5e-3, log=True),
            "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-3, log=True),
            "dropout": trial.suggest_float("dropout", 0.0, 0.3),
            "optimizer_name": trial.suggest_categorical("optimizer_name", list(OPTIMIZER_CHOICES)),
            "lambda_reconstruction": trial.suggest_float(
                "lambda_reconstruction", 1e-2, 1.0, log=True
            ),
            "lambda_mutual_information": trial.suggest_categorical(
                "lambda_mutual_information", list(LAMBDA_MI_CHOICES)
            ),
            "lambda_gate_deviation": trial.suggest_categorical(
                "lambda_gate_deviation", list(LAMBDA_DEV_CHOICES)
            ),
            # alpha=0 is excluded from the search range: it structurally freezes
            # g == 1 (PerSampleEdgeGateDecoder's zero-init identity), switching
            # the whole gate mechanism off.
            "alpha": trial.suggest_float("alpha", 0.05, 0.5),
        }

        labels_by_seed: list[np.ndarray] = []
        reconstruction_losses: list[float] = []

        for seed_position, seed in enumerate(seeds):
            model = build_model_fn(meta, params)
            loss_fn = build_loss_fn(meta, params)
            result = entrenar_fn(
                model,
                loss_fn,
                X_past,
                epochs=epochs,
                batch_size=meta.get("batch_size", 1024),
                lr=params["lr"],
                weight_decay=params["weight_decay"],
                optimizer_name=params["optimizer_name"],
                seed=seed,
            )
            reconstruction_loss = float(result["reconstruction_loss_raw"])
            reconstruction_losses.append(reconstruction_loss)

            # Feasibility prune: deterministic, on the FIRST seed only, before
            # any clustering work happens.
            if seed_position == 0 and reconstruction_loss > tau:
                raise optuna.TrialPruned()

            gate_means = extraer_gate_means_fn(result)
            kmeans = KMeans(n_clusters=k_search, n_init=10, random_state=seed).fit(gate_means)
            cluster_sizes = np.bincount(kmeans.labels_)
            minority_fraction = float(cluster_sizes.min()) / float(cluster_sizes.sum())
            if minority_fraction < _MIN_MINORITY_CLUSTER_FRACTION:
                return _DEGENERATE_PARTITION_SENTINEL

            labels_by_seed.append(kmeans.labels_)

            if seed_position == 1:
                interim_ari = mean_pairwise_ari(labels_by_seed)
                trial.report(interim_ari, step=0)
                if trial.should_prune():
                    raise optuna.TrialPruned()

        if float(np.mean(reconstruction_losses)) > tau:
            return _DEGENERATE_PARTITION_SENTINEL

        return mean_pairwise_ari(labels_by_seed)

    return objective


# ---------------------------------------------------------------------------
# Sweep-report helpers
# ---------------------------------------------------------------------------


def resumen_barrido_lambda_dev(
    resultados_por_lambda: Mapping[float, np.ndarray],
) -> pd.DataFrame:
    """Assemble the `lambda_dev` sweep report: gate-variance/effective-rank
    (via `estadistico_colapso`) reported against EVERY swept `lambda_dev`
    value, including `0.0`, so a null collapse result can never be blamed
    on the regularizer alone.

    `resultados_por_lambda` maps each swept `lambda_dev` value to its
    `(n_vano, n_edges)` gate-means matrix.
    """
    from chec_impacto.interpretability.mgcecdl_graph import estadistico_colapso

    rows = []
    for lambda_dev, gate_means in resultados_por_lambda.items():
        stats = estadistico_colapso(gate_means)
        rows.append(
            {
                "lambda_dev": float(lambda_dev),
                "variance": stats["variance"],
                "effective_rank": stats["effective_rank"],
                "is_collapsed": stats["is_collapsed"],
            }
        )
    return pd.DataFrame(rows).sort_values("lambda_dev").reset_index(drop=True)


def resumen_barrido_lambda_mi(
    resultados_por_lambda: Mapping[float, Mapping[str, Any]],
) -> pd.DataFrame:
    """Assemble the `lambda_MI` sweep report: the ACHIEVED
    `mutual_information_normalized` per swept `lambda_MI` value -- not just
    its loss share -- so the sweep cannot silently be read as "higher
    lambda always means more achieved MI" from the loss term alone.

    `resultados_por_lambda` maps each swept `lambda_MI` value to the dict
    returned by `entrenar_gated_autoencoder` (or an equivalent stub).
    """
    rows = []
    for lambda_mi, result in resultados_por_lambda.items():
        rows.append(
            {
                "lambda_mutual_information": float(lambda_mi),
                "mutual_information_normalized": float(result["mutual_information_normalized"]),
                "mutual_information_loss": float(result["mutual_information_loss"]),
                "reconstruction_loss_raw": float(
                    result.get("reconstruction_loss_raw", float("nan"))
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("lambda_mutual_information").reset_index(drop=True)
