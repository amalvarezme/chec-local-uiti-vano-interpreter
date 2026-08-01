# UITI_VANO Regression Baseline — `uiti-vano-regression` Experiment Family

Pinned comparison floor for any Kaggle run of this family. Source: local notebooks
`02.1_mgcecdl_regression_embeddings.ipynb` (removed from `notebooks/project_flow/`; recoverable from
git history) and `01.2_uiti_vano_kmeans.ipynb` (formerly `10_uiti_vano_kmeans.ipynb`). `MGCECDLRegressor`,
`MGCECDLRegressionLoss`, and `KernelDensityWeightedMSELoss` live on `main` at
`src/chec_impacto/models/mgcecdl.py` (originally authored in worktree
`worktree-agent-a4051edb7e841e0f9`, now landed).

## Local Run Conditions

- Hardware: `device=mps:0` (Apple Silicon MPS), ~3.2 s/epoch — **not CPU**.
- Loss sweep: 20 epochs per candidate loss (`mse`, `huber`, `kernel_weighted_mse`), best
  selected by `mae_original.idxmin()`.
- Optuna: `GPSampler` + `MedianPruner`, 10 trials at 20 epochs each.
- Final retrain: 60 epochs, using the selected loss shape and Optuna's best hyperparameters.

## Pinned Metrics

| Metric | Value | Role |
|---|---|---|
| `mae_original` | 126.402 | **Primary** — the Kaggle run must report this next to the baseline and state improved/not |
| `r2_original` | -0.027 | Secondary diagnostic |
| `r2_transformed` | 0.284 | Secondary diagnostic |
| `ARI` (auto K) | 0.0000 | Secondary diagnostic (selected K=2 vs ground-truth K=2) |
| `ARI` (K=4 fixed) | 0.1115 | Secondary diagnostic |

## Methodology Order (must be preserved)

1. Loss-shape sweep: `mse` / `huber` / `kernel_weighted_mse` — select the best by
   `mae_original.idxmin()`.
2. Optuna search: `GPSampler` + `MedianPruner`. Kaggle `full` mode must increase the budget
   versus this local run (trials > 10, epochs not reduced).
3. Final retrain with the selected loss shape and Optuna's best hyperparameters.
4. Embeddings extraction from the retrained model.
5. K-Means + silhouette scan, `K = 2..8`.
6. ARI triangulation against Part A (the classification-side clustering).

## Precondition Guard — In-Notebook Mirror

Every notebook in this family must open with an assert cell mirroring the skill's
precondition guard, so a stale or missing Kaggle `chec-impacto-src` dataset attach fails fast
before any model/loss cell runs. `MGCECDLRegressor`, `MGCECDLRegressionLoss`, and
`KernelDensityWeightedMSELoss` already live on `main` at `src/chec_impacto/models/mgcecdl.py`,
so a guard trip on Kaggle means the attached `chec-impacto-src` dataset is out of date, not
that the code is missing from the repo:

```python
try:
    from chec_impacto.models.mgcecdl import (
        MGCECDLRegressor,
        MGCECDLRegressionLoss,
        KernelDensityWeightedMSELoss,
    )
except ImportError as exc:
    raise SystemExit(
        "MGCECDLRegressor/MGCECDLRegressionLoss not importable — the attached src dataset "
        "(chec-impacto-src) appears to be missing or out of date. These classes live in "
        "src/chec_impacto/models/mgcecdl.py on main; re-package/version the chec-impacto-src "
        "Kaggle dataset from the current main checkout and re-attach it to this kernel."
    ) from exc
```

## Kaggle Budget Delta (this family only)

`full` mode must increase Optuna trials and/or epochs versus the local baseline above, and
request a GPU accelerator — same code, same metric definitions, so the Kaggle result stays
comparable to the numbers pinned in this file. A GPU accelerator alone is not automatically
more compute than the local MPS run; the guaranteed increase is trials × epochs.
