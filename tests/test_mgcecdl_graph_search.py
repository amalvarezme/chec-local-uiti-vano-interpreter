"""Unit tests for the Optuna search objective for the per-sample edge-gate
autoencoder (`src/chec_impacto/models/mgcecdl_graph_search.py`).

Covers PR2 of notebook-12-criticality-representation: the search-seed
quarantine (design D3), the feasibility prune against `tau`, the degenerate-
partition sentinel, and the `lambda_dev`/`lambda_MI` sweep-report helpers.
See:
  - spec: sdd/notebook-12-criticality-representation/spec (capability
    `graph-regime-clustering`)
  - design: sdd/notebook-12-criticality-representation/design (D3, D4,
    "Optuna objective (implementation)")

Every test here stubs `entrenar_fn`/gate extraction -- no real training runs
(the runtime harness is a 2-trial stub Optuna study), matching the Suggested
Work Units table in the tasks artifact.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import optuna
import pytest

from chec_impacto.models.mgcecdl_graph_search import (
    LAMBDA_DEV_CHOICES,
    LAMBDA_MI_CHOICES,
    construir_objetivo_gated,
    mean_pairwise_ari,
    resumen_barrido_lambda_dev,
    resumen_barrido_lambda_mi,
)

SEARCH_MODULE_PATH = Path("src/chec_impacto/models/mgcecdl_graph_search.py")

optuna.logging.set_verbosity(optuna.logging.WARNING)


def _run_single_trial(objective, seed: int = 0) -> optuna.Study:
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.RandomSampler(seed=seed),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=0),
    )
    study.optimize(objective, n_trials=1, catch=())
    return study


# ---------------------------------------------------------------------------
# 2.27 / 2.29 / 2.31 / 2.33 -- construir_objetivo_gated
# ---------------------------------------------------------------------------


def test_construir_objetivo_gated_seed_quarantine() -> None:
    """The search must train EXACTLY `len(seeds)` times per trial, using the
    search-time seed set `{0,1,2}` -- disjoint from the acceptance gate's
    `{10..14}` -- and `k_search=4` must never surface as "the" reported K:
    the objective's return value is always an ARI float."""
    call_log: list[dict] = []

    def _stub_entrenar(model, loss_fn, X_past, *, seed, **kwargs):
        call_log.append({"seed": seed})
        return {"model": model, "reconstruction_loss_raw": 0.05}

    def _stub_build_model(meta, params):
        return object()

    def _stub_build_loss(meta, params):
        return object()

    # Identical cluster assignments across every seed -> ARI == 1.0 exactly,
    # so the returned value is unambiguous and clearly not `k_search` (4).
    fixed_labels = np.array([0] * 5 + [1] * 5 + [2] * 5 + [3] * 5)

    def _stub_extraer_gate_means(entrenar_result):
        del entrenar_result
        return fixed_labels.reshape(-1, 1).astype(float)

    objective = construir_objetivo_gated(
        X_past=np.zeros((20, 3), dtype=np.float32),
        meta={"circuito": np.zeros(20), "fid_vano": np.arange(20)},
        tau=1.0,
        seeds=(0, 1, 2),
        k_search=4,
        epochs=1,
        entrenar_fn=_stub_entrenar,
        build_model_fn=_stub_build_model,
        build_loss_fn=_stub_build_loss,
        extraer_gate_means_fn=_stub_extraer_gate_means,
    )

    study = _run_single_trial(objective)

    assert len(call_log) == 3, "must train exactly len(seeds)=3 times per trial"
    assert [entry["seed"] for entry in call_log] == [0, 1, 2]
    assert study.best_value != 4.0
    assert study.best_value == pytest.approx(1.0)


def test_objective_excludes_future_uiti_vano() -> None:
    """Structural guard: the objective's `meta` never needs, and the module
    never reads, any future-window value -- grep-guard the module source for
    the string "future" entirely (D3/D4 quarantine), excluding the standard
    `from __future__ import annotations` idiom every module in this repo
    uses."""
    source_lines = SEARCH_MODULE_PATH.read_text(encoding="utf-8").splitlines()
    relevant_lines = [
        line for line in source_lines if not line.strip().startswith("from __future__")
    ]
    assert "future" not in "\n".join(relevant_lines).lower()

    # And functionally: a meta dict with NO future-window key at all must be
    # sufficient to build and run the objective.
    def _stub_entrenar(model, loss_fn, X_past, *, seed, **kwargs):
        return {"model": model, "reconstruction_loss_raw": 0.05}

    def _stub_extraer_gate_means(entrenar_result):
        del entrenar_result
        return np.array([[0.0], [0.0], [1.0], [1.0]])

    objective = construir_objetivo_gated(
        X_past=np.zeros((4, 2), dtype=np.float32),
        meta={"circuito": np.zeros(4), "fid_vano": np.arange(4)},
        tau=1.0,
        seeds=(0, 1),
        k_search=2,
        epochs=1,
        entrenar_fn=_stub_entrenar,
        build_model_fn=lambda meta, params: object(),
        build_loss_fn=lambda meta, params: object(),
        extraer_gate_means_fn=_stub_extraer_gate_means,
    )
    _run_single_trial(objective)  # must not raise / must not need a future key


def test_objective_returns_sentinel_on_degenerate_partition() -> None:
    """A near-degenerate partition (minority cluster < 1% of vanos) must
    return the `-1.0` sentinel, never a spuriously high ARI."""
    n_vano = 200

    def _stub_entrenar(model, loss_fn, X_past, *, seed, **kwargs):
        return {"model": model, "reconstruction_loss_raw": 0.05}

    def _stub_build(meta, params):
        return object()

    def _stub_extraer_gate_means(entrenar_result):
        del entrenar_result
        # 199 points at the origin, 1 far outlier -> KMeans(k_search=4) isolates
        # the outlier into its own singleton (0.5% << 1% minimum minority fraction).
        gate_means = np.zeros((n_vano, 2))
        gate_means[-1] = [1000.0, 1000.0]
        return gate_means

    objective = construir_objetivo_gated(
        X_past=np.zeros((n_vano, 2), dtype=np.float32),
        meta={"circuito": np.zeros(n_vano), "fid_vano": np.arange(n_vano)},
        tau=1.0,
        seeds=(0, 1, 2),
        k_search=4,
        epochs=1,
        entrenar_fn=_stub_entrenar,
        build_model_fn=_stub_build,
        build_loss_fn=_stub_build,
        extraer_gate_means_fn=_stub_extraer_gate_means,
    )

    study = _run_single_trial(objective)
    assert study.best_value == pytest.approx(-1.0)


def test_feasibility_prune_above_tau() -> None:
    """If seed-0's `reconstruction_loss_raw > tau`, the trial must be pruned
    BEFORE seeds 1/2 ever train."""
    call_log: list[int] = []

    def _stub_entrenar(model, loss_fn, X_past, *, seed, **kwargs):
        call_log.append(seed)
        return {"model": model, "reconstruction_loss_raw": 999.0}  # always above any small tau

    objective = construir_objetivo_gated(
        X_past=np.zeros((4, 2), dtype=np.float32),
        meta={"circuito": np.zeros(4), "fid_vano": np.arange(4)},
        tau=0.5,
        seeds=(0, 1, 2),
        k_search=2,
        epochs=1,
        entrenar_fn=_stub_entrenar,
        build_model_fn=lambda meta, params: object(),
        build_loss_fn=lambda meta, params: object(),
        extraer_gate_means_fn=lambda result: np.array([[0.0], [1.0]]),
    )

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.RandomSampler(seed=0),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=0),
    )
    study.optimize(objective, n_trials=1, catch=())

    assert call_log == [0], "seeds 1/2 must never train once seed 0 exceeds tau"
    assert study.trials[0].state == optuna.trial.TrialState.PRUNED


# ---------------------------------------------------------------------------
# 2.35 / 2.37 -- lambda_dev / lambda_MI sweep-report helpers
# ---------------------------------------------------------------------------


def test_lambda_dev_sweep_includes_zero_and_reports_variance() -> None:
    assert 0.0 in LAMBDA_DEV_CHOICES

    rng = np.random.default_rng(0)
    resultados_por_lambda = {
        0.0: rng.uniform(0.4, 1.6, size=(20, 4)),  # deliberately NOT collapsed
        1e-2: np.ones((20, 4)),  # deliberately collapsed
    }

    report = resumen_barrido_lambda_dev(resultados_por_lambda)

    assert set(report["lambda_dev"]) == {0.0, 1e-2}
    row_zero = report.loc[report["lambda_dev"] == 0.0].iloc[0]
    row_reg = report.loc[report["lambda_dev"] == 1e-2].iloc[0]
    assert row_zero["variance"] > row_reg["variance"]
    assert bool(row_reg["is_collapsed"]) is True
    assert bool(row_zero["is_collapsed"]) is False


def test_lambda_mi_sweep_reports_achieved_mi_not_just_loss_share() -> None:
    assert set(LAMBDA_MI_CHOICES) == {0.01, 0.1, 0.3, 1.0}

    resultados_por_lambda = {
        0.01: {
            "mutual_information_normalized": 0.000957,
            "mutual_information_loss": 0.10,
            "reconstruction_loss_raw": 0.5,
        },
        0.1: {
            "mutual_information_normalized": 0.0021,
            "mutual_information_loss": 0.09,
            "reconstruction_loss_raw": 0.5,
        },
        0.3: {
            "mutual_information_normalized": 0.0033,
            "mutual_information_loss": 0.08,
            "reconstruction_loss_raw": 0.5,
        },
        1.0: {
            "mutual_information_normalized": 0.0040,
            "mutual_information_loss": 0.07,
            "reconstruction_loss_raw": 0.5,
        },
    }

    report = resumen_barrido_lambda_mi(resultados_por_lambda)

    assert list(report["lambda_mutual_information"]) == [0.01, 0.1, 0.3, 1.0]
    assert list(report["mutual_information_normalized"]) == [0.000957, 0.0021, 0.0033, 0.0040]
    # The achieved MI must NOT simply track the loss share (loss decreases while
    # achieved MI increases here -- the whole point of reporting both).
    assert report["mutual_information_normalized"].is_monotonic_increasing
    assert report["mutual_information_loss"].is_monotonic_decreasing


def test_mean_pairwise_ari_helper() -> None:
    identical = [np.array([0, 0, 1, 1]), np.array([0, 0, 1, 1]), np.array([0, 0, 1, 1])]
    assert mean_pairwise_ari(identical) == pytest.approx(1.0)

    single = [np.array([0, 0, 1, 1])]
    assert np.isnan(mean_pairwise_ari(single))


# ---------------------------------------------------------------------------
# PR1 <-> PR2 integration seam. The sweep-summary tests above stub `entrenar_fn`,
# which is exactly why the real contract between `entrenar_gated_autoencoder`'s
# result dict and what `resumen_barrido_lambda_mi` reads from it went unchecked
# and shipped broken. This exercises the seam with real training.
# ---------------------------------------------------------------------------


def test_real_training_result_satisfies_the_lambda_mi_sweep_contract() -> None:
    import numpy as np

    from chec_impacto.models.mgcecdl_graph import entrenar_gated_autoencoder

    from tests.test_mgcecdl_graph_gates import (  # noqa: PLC0415
        _tiny_gated_model,
        _tiny_loss,
    )

    gated = _tiny_gated_model(alpha=0.3)
    loss_fn = _tiny_loss(lambda_gate_deviation=0.01)
    n_features = int(gated.adjacency.shape[0])
    X_past = np.random.default_rng(7).normal(size=(32, n_features)).astype(np.float32)

    result = entrenar_gated_autoencoder(
        gated,
        loss_fn,
        X_past,
        epochs=1,
        batch_size=8,
        lr=1e-3,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=7,
        device="cpu",
    )

    # Every key `resumen_barrido_lambda_mi` dereferences without a default must
    # actually be produced by a real run, not only by the test stubs.
    for required_key in ("mutual_information_normalized", "mutual_information_loss"):
        assert required_key in result, (
            f"entrenar_gated_autoencoder did not return '{required_key}', which "
            "resumen_barrido_lambda_mi reads unconditionally -- the sweep would raise KeyError"
        )

    summary = resumen_barrido_lambda_mi({0.01: result})
    assert len(summary) == 1
    assert np.isfinite(summary["mutual_information_normalized"].iloc[0])
    # The achieved value is a normalized quantity and must stay in its range.
    assert 0.0 <= summary["mutual_information_normalized"].iloc[0] <= 1.0
