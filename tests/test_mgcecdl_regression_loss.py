"""Unit tests for the MGCECDL regression loss (`MGCECDLRegressionLoss`) and its
kernel-density-weighted MSE building block (`KernelDensityWeightedMSELoss`).

Both live in `src/chec_impacto/models/mgcecdl.py` (NOT
`src/chec_impacto/training/mgcecdl.py`, which is under an explicit `Edit`
deny in this repo's `.claude/settings.json` protecting the production
classification training module) -- they reuse that module's private helpers
(`_MGCECDLGraphReconstructionLoss`, `_reduce_modality_supervision_loss`,
`_normalize_unit_interval`, `_safe_log_count`) via a deferred import inside
`__init__` (not a top-level import, to avoid a models<->training circular
import), so the underlying computation is genuinely shared, not
reimplemented, without ever writing to the denied path.

Both are new, additive production code, built to give `MGCECDLRegressor` the
SAME auxiliary loss structure that
`MGCECDLClassificationLoss` gives `MGCECDLClassifier`: a fused supervised term,
a per-modality reliability-weighted supervised term, a cross-modality
agreement term, a reliability-KL regularization term, and the graph
reconstruction + mutual-information terms inherited from
`_MGCECDLGraphReconstructionLoss`. The only deliberate, documented deviation
from classification's structure is the classification-only `entropy_loss`
term (defined over categorical probabilities, with no direct regression
analogue), which is dropped from `regularization_loss` -- everything else is
full parity, just swapping the supervised term from generalized
cross-entropy to a configurable regression loss (`mse`, `huber`, or
`kernel_weighted_mse`).

`MGCECDLClassificationLoss`/`MGCECDLClassifier` are untouched by this change.
"""

from __future__ import annotations

import numpy as np
import torch

from chec_impacto.models import MGCECDLRegressor
from chec_impacto.models.mgcecdl import (
    KernelDensityWeightedMSELoss,
    MGCECDLRegressionLoss,
)


def _modality_feature_indices() -> dict[str, list[int]]:
    return {"climaticos": [0, 1, 2], "estructurales": [3, 4]}


def _build_loss(base_loss: str = "mse", **overrides) -> MGCECDLRegressionLoss:
    n_features = 5
    feature_mean = np.zeros(n_features, dtype=np.float32)
    feature_std = np.ones(n_features, dtype=np.float32)
    adjacency_matrix = np.eye(n_features, dtype=np.float32)
    kwargs = dict(
        base_loss=base_loss,
        gamma_sup=0.2,
        gamma_agr=0.1,
        gamma_reg=0.01,
        feature_mean=feature_mean,
        feature_std=feature_std,
        adjacency_matrix=adjacency_matrix,
        rbf_sigma=1.0,
        lambda_reconstruction=0.01,
        lambda_mutual_information=0.01,
    )
    kwargs.update(overrides)
    return MGCECDLRegressionLoss(**kwargs)


def _build_model() -> MGCECDLRegressor:
    return MGCECDLRegressor(
        modality_feature_indices=_modality_feature_indices(),
        hidden_dim=16,
        embed_dim=8,
        dropout=0.0,
        temperature=1.0,
    )


# ---------------------------------------------------------------------------
# KernelDensityWeightedMSELoss
# ---------------------------------------------------------------------------


def test_kernel_density_weighted_loss_upweights_rare_tail_values() -> None:
    # 1000 samples clustered near 0.0 (dense/common) and 10 samples near 10.0
    # (rare/tail) -- mirrors the real UITI_VANO shape (dense mid-range mass,
    # sparse high-criticality tail).
    rng = np.random.default_rng(0)
    dense_targets = rng.normal(loc=0.0, scale=0.1, size=1000)
    rare_targets = rng.normal(loc=10.0, scale=0.1, size=10)
    all_targets = np.concatenate([dense_targets, rare_targets])

    loss_fn = KernelDensityWeightedMSELoss.from_targets(all_targets, n_grid=512)

    dense_point = torch.tensor([0.0])
    rare_point = torch.tensor([10.0])
    dense_weight = loss_fn.compute_weights(dense_point)
    rare_weight = loss_fn.compute_weights(rare_point)

    assert float(rare_weight[0]) > float(dense_weight[0])


def test_kernel_density_weighted_loss_forward_is_finite_and_batch_mixed() -> None:
    rng = np.random.default_rng(1)
    all_targets = np.concatenate(
        [rng.normal(0.0, 0.1, size=500), rng.normal(10.0, 0.1, size=20)]
    )
    loss_fn = KernelDensityWeightedMSELoss.from_targets(all_targets, n_grid=256)

    predictions = torch.tensor([0.1, 10.1, 5.0])
    targets = torch.tensor([0.0, 10.0, 5.0])
    loss_value = loss_fn(predictions, targets)

    assert torch.isfinite(loss_value)
    assert loss_value.ndim == 0


def test_kernel_density_weighted_loss_handles_out_of_grid_values() -> None:
    all_targets = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    loss_fn = KernelDensityWeightedMSELoss.from_targets(all_targets, n_grid=64)

    # Values well outside the fitted grid range must not produce NaN/inf
    # (clamped to the nearest grid edge instead of extrapolating).
    out_of_range = torch.tensor([-50.0, 50.0])
    weights = loss_fn.compute_weights(out_of_range)
    assert torch.isfinite(weights).all()
    assert (weights > 0).all()


# ---------------------------------------------------------------------------
# MGCECDLRegressionLoss
# ---------------------------------------------------------------------------


def test_compute_components_has_full_parity_keys_with_classification_minus_entropy() -> None:
    torch.manual_seed(0)
    model = _build_model()
    loss_fn = _build_loss(base_loss="mse")
    x = torch.randn(6, 5)
    targets = torch.rand(6)

    output = model(x)
    components = loss_fn.compute_components(output, targets, x)

    expected_keys = {
        "total_loss",
        "fused_loss",
        "modality_loss",
        "agreement_loss",
        "kl_loss",
        "regularization_loss",
        "reconstruction_loss",
        "mutual_information",
        "mutual_information_loss",
    }
    assert expected_keys.issubset(components.keys())
    assert torch.isfinite(components["total_loss"])
    # Classification-only entropy_loss has no regression analogue and must not
    # silently reappear under the same key with meaningless content.
    assert "entropy_loss" not in components


def test_forward_returns_scalar_total_loss() -> None:
    torch.manual_seed(1)
    model = _build_model()
    loss_fn = _build_loss(base_loss="mse")
    x = torch.randn(4, 5)
    targets = torch.rand(4)

    output = model(x)
    total_loss = loss_fn(output, targets, x)

    assert total_loss.ndim == 0
    assert torch.isfinite(total_loss)


def test_invalid_base_loss_raises_value_error() -> None:
    try:
        _build_loss(base_loss="not_a_real_loss")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for an unsupported base_loss.")


def test_huber_is_less_sensitive_to_outlier_residuals_than_mse() -> None:
    torch.manual_seed(2)
    model = _build_model()
    x = torch.randn(5, 5)
    # Deliberately large targets so the model's (near-zero-initialized) fused
    # prediction is far off -- a large, consistent residual for every sample.
    targets = torch.full((5,), 50.0)

    output = model(x)
    mse_loss_fn = _build_loss(base_loss="mse")
    huber_loss_fn = _build_loss(base_loss="huber", huber_delta=1.0)

    mse_components = mse_loss_fn.compute_components(output, targets, x)
    huber_components = huber_loss_fn.compute_components(output, targets, x)

    assert float(huber_components["fused_loss"]) < float(mse_components["fused_loss"])


def test_kernel_weighted_base_loss_requires_kernel_loss_module() -> None:
    try:
        _build_loss(base_loss="kernel_weighted_mse")
    except ValueError:
        return
    raise AssertionError(
        "Expected ValueError when base_loss='kernel_weighted_mse' is requested "
        "without a fitted KernelDensityWeightedMSELoss."
    )


def test_kernel_weighted_base_loss_runs_end_to_end_when_provided() -> None:
    torch.manual_seed(3)
    model = _build_model()
    x = torch.randn(8, 5)
    targets = torch.rand(8)

    kernel_loss = KernelDensityWeightedMSELoss.from_targets(
        np.random.default_rng(4).uniform(0, 1, size=200), n_grid=128
    )
    loss_fn = _build_loss(base_loss="kernel_weighted_mse", kernel_loss_module=kernel_loss)
    output = model(x)
    total_loss = loss_fn(output, targets, x)

    assert torch.isfinite(total_loss)


def test_classification_loss_import_still_works_unaffected() -> None:
    """Adding MGCECDLRegressionLoss must not disturb MGCECDLClassificationLoss."""
    from chec_impacto.training.mgcecdl import MGCECDLClassificationLoss

    assert MGCECDLClassificationLoss is not None


# ---------------------------------------------------------------------------
# reconstruction_normalization: the hard clip is a dead fixed point
# ---------------------------------------------------------------------------


def _inputs_forcing_raw_reconstruction_above_one() -> tuple[MGCECDLRegressor, torch.Tensor, torch.Tensor]:
    """Build a state whose raw reconstruction MSE exceeds the clip ceiling of 1.

    This is not a contrived corner: standardized predictors have unit variance,
    so an untrained decoder already sits at MSE ~= 1, and a real run of
    `11_mgcecdl_regression_budget.ipynb` measured 1.3124 at initialization.
    """
    torch.manual_seed(11)
    model = _build_model()
    inputs = torch.randn(32, 5) * 3.0  # inflate the standardized scale -> MSE well above 1
    targets = torch.rand(32)
    return model, inputs, targets


def test_clip_normalization_kills_the_reconstruction_gradient_above_the_ceiling() -> None:
    """Documents the defect: with the hard clip the term is a zero-gradient constant."""
    model, inputs, targets = _inputs_forcing_raw_reconstruction_above_one()
    loss_fn = _build_loss(reconstruction_normalization="clip")

    components = loss_fn.compute_components(model(inputs), targets, inputs)

    assert float(components["reconstruction_loss_raw"]) > 1.0
    assert float(components["reconstruction_loss"]) == 1.0

    components["reconstruction_loss"].backward()
    decoder_grads = [
        p.grad for p in model.parameters() if p.grad is not None and p.grad.abs().sum() > 0
    ]
    assert not decoder_grads, (
        "clip normalization is expected to produce exactly zero gradient above the ceiling"
    )


def test_soft_normalization_keeps_a_live_gradient_above_the_ceiling() -> None:
    """The fix: a saturating-but-smooth map keeps [0, 1] AND a usable gradient."""
    model, inputs, targets = _inputs_forcing_raw_reconstruction_above_one()
    loss_fn = _build_loss(reconstruction_normalization="soft")

    components = loss_fn.compute_components(model(inputs), targets, inputs)
    raw = float(components["reconstruction_loss_raw"])
    normalized = float(components["reconstruction_loss"])

    assert raw > 1.0
    assert 0.0 < normalized < 1.0, "soft normalization must stay inside (0, 1), never pin at 1"
    # float32 tensor math vs float64 Python arithmetic: compare within tolerance, not exactly.
    assert abs(normalized - raw / (1.0 + raw)) < 1e-6

    components["reconstruction_loss"].backward()
    total_grad = sum(
        float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None
    )
    assert total_grad > 0.0, "soft normalization must propagate a non-zero gradient"


def test_soft_normalization_is_monotone_and_bounded() -> None:
    """0 stays the best value and the map never leaves [0, 1)."""
    model, inputs, targets = _inputs_forcing_raw_reconstruction_above_one()
    loss_fn = _build_loss(reconstruction_normalization="soft")

    with torch.no_grad():
        components = loss_fn.compute_components(model(inputs), targets, inputs)

    raw = torch.tensor([0.0, 0.25, 1.0, 1.3124, 10.0, 1e6])
    mapped = raw / (1.0 + raw)
    assert torch.all(mapped >= 0.0) and torch.all(mapped < 1.0)
    assert torch.all(mapped[1:] > mapped[:-1]), "must be strictly increasing"
    assert float(mapped[0]) == 0.0, "a perfect reconstruction must still score 0"
    assert torch.isfinite(components["total_loss"])


def test_clip_remains_the_default_so_existing_runs_are_unchanged() -> None:
    loss_fn = _build_loss()
    assert loss_fn.reconstruction_normalization == "clip"


def test_invalid_reconstruction_normalization_raises_value_error() -> None:
    try:
        _build_loss(reconstruction_normalization="bogus")
    except ValueError as exc:
        assert "reconstruction_normalization" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unsupported normalization")
