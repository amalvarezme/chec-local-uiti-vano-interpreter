"""Unit tests for the per-sample edge-gate autoencoder building blocks
(`src/chec_impacto/models/mgcecdl_graph.py`).

This module wraps `MGCECDLRegressor` as an autoencoder: a per-sample gate
head modulates the fixed expert adjacency, the model is trained ONLY against
its own reconstruction of the original input (never a supervised target),
and the resulting per-sample edge gates are the criticality representation
downstream notebooks cluster. See:
  - spec: sdd/notebook-12-criticality-representation/spec (capability
    `per-sample-edge-gates`)
  - design: sdd/notebook-12-criticality-representation/design (D1, D2, D6)

All fixtures are a tiny synthetic (B=8, p=6, E=5) graph -- dimensions are
read from the fixture data itself everywhere, never hardcoded as literals in
the module under test (see `test_no_forbidden_literal_counts_in_gate_module`).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import numpy as np
import pytest
import torch

from chec_impacto.models.mgcecdl import MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import (
    GatedSelfSupervisedLoss,
    GraphEdgeIndex,
    GraphGatedMGCECDLRegressor,
    PerSampleEdgeGateDecoder,
    construir_edge_index,
    entrenar_gated_autoencoder,
    reinyectar_target_como_feature,
)

GATE_MODULE_PATH = Path("src/chec_impacto/models/mgcecdl_graph.py")

# ---------------------------------------------------------------------------
# Tiny synthetic graph fixture (B=8, p=6, E=5) -- never used as a literal
# inside the module under test, only inside these tests.
# ---------------------------------------------------------------------------

_FEATURES = ["a", "b", "c", "d", "e", "f"]
_EDGES = [
    {"source": "a", "target": "b", "weight": 0.5},
    {"source": "b", "target": "c", "weight": 0.8},
    {"source": "c", "target": "d", "weight": 0.3},
    {"source": "d", "target": "e", "weight": 0.6},
    {"source": "e", "target": "f", "weight": 0.9},
]
_MODALITY_FEATURE_INDICES = {"climaticos": [0, 1, 2], "estructurales": [3, 4, 5]}


def _tiny_adjacency() -> np.ndarray:
    positions = {name: index for index, name in enumerate(_FEATURES)}
    matrix = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for edge in _EDGES:
        matrix[positions[edge["source"]], positions[edge["target"]]] = edge["weight"]
    return matrix


def _tiny_edge_index() -> GraphEdgeIndex:
    return construir_edge_index(_tiny_adjacency(), _FEATURES, _EDGES)


def _tiny_base_model(dropout: float = 0.0) -> MGCECDLRegressor:
    return MGCECDLRegressor(
        modality_feature_indices=_MODALITY_FEATURE_INDICES,
        hidden_dim=16,
        embed_dim=4,
        dropout=dropout,
        temperature=1.0,
    )


def _tiny_gated_model(alpha: float = 0.3, dropout: float = 0.0) -> GraphGatedMGCECDLRegressor:
    base = _tiny_base_model(dropout=dropout)
    gated = GraphGatedMGCECDLRegressor(
        base=base, adjacency=_tiny_adjacency(), edge_index=_tiny_edge_index(), alpha=alpha
    )
    gated.eval()
    return gated


def _tiny_loss(lambda_gate_deviation: float = 0.0) -> GatedSelfSupervisedLoss:
    n_features = len(_FEATURES)
    return GatedSelfSupervisedLoss(
        feature_mean=np.zeros(n_features, dtype=np.float32),
        feature_std=np.ones(n_features, dtype=np.float32),
        adjacency_matrix=_tiny_adjacency(),
        rbf_sigma=1.0,
        lambda_reconstruction=0.01,
        lambda_mutual_information=0.01,
        lambda_gate_deviation=lambda_gate_deviation,
        reconstruction_normalization="soft",
    )


def _tiny_batch(batch_size: int = 8, seed: int = 0) -> torch.Tensor:
    generator = torch.Generator().manual_seed(seed)
    return torch.randn(batch_size, len(_FEATURES), generator=generator)


# ---------------------------------------------------------------------------
# 1.1 / 1.3 -- GraphEdgeIndex / construir_edge_index
# ---------------------------------------------------------------------------


def test_edge_index_dims_derived_from_adjacency() -> None:
    edge_index = _tiny_edge_index()

    assert edge_index.n_edges == len(_EDGES)
    assert edge_index.pairs.shape == (len(_EDGES), 2)
    assert edge_index.weights.shape == (len(_EDGES),)
    assert len(edge_index.names) == len(_EDGES)


def test_no_forbidden_literal_counts_in_gate_module() -> None:
    """No literal feature/edge count may appear in the gate module's source.

    `p`/`E` must always be derived at runtime from the adjacency/edge index,
    never hardcoded -- a literal `70`/`74`/`75`/`56`/`71`/`73` here would be
    exactly the kind of silent, brittle assumption this guard exists to
    catch (see the launch contract's HARD CONSTRAINTS).
    """
    source = GATE_MODULE_PATH.read_text(encoding="utf-8")
    forbidden_pattern = re.compile(r"\b(?:70|74|75|56|71|73)\b")
    matches = forbidden_pattern.findall(source)
    assert not matches, f"forbidden literal count(s) found in {GATE_MODULE_PATH}: {matches}"


def test_edge_index_alignment_by_name() -> None:
    """Edges must align to feature POSITIONS via NAME lookup, never via the
    positional order of `preserved_edges` or of `features`."""
    shuffled_features = list(reversed(_FEATURES))
    shuffled_edges = list(reversed(_EDGES))
    adjacency = np.zeros((len(shuffled_features), len(shuffled_features)), dtype=np.float32)
    positions = {name: index for index, name in enumerate(shuffled_features)}
    for edge in shuffled_edges:
        adjacency[positions[edge["source"]], positions[edge["target"]]] = edge["weight"]

    edge_index = construir_edge_index(adjacency, shuffled_features, shuffled_edges)

    expected_names = {(edge["source"], edge["target"]) for edge in _EDGES}
    assert set(edge_index.names) == expected_names

    name_to_pair = dict(zip(edge_index.names, (tuple(pair) for pair in edge_index.pairs)))
    for edge in _EDGES:
        source_index = positions[edge["source"]]
        target_index = positions[edge["target"]]
        assert name_to_pair[(edge["source"], edge["target"])] == (source_index, target_index)


# ---------------------------------------------------------------------------
# 1.5 -- reinyectar_target_como_feature (D5)
# ---------------------------------------------------------------------------


def test_reinjection_row_aligned_not_joined() -> None:
    n_samples = 8
    X = np.arange(n_samples * 3, dtype=np.float32).reshape(n_samples, 3)
    y = np.arange(100, 100 + n_samples, dtype=np.float32).reshape(n_samples, 1)
    # `df_original_copy` deliberately has a SCRAMBLED, non-contiguous index --
    # any implementation that joins on it instead of using `resultado["y"]`
    # positionally would misalign here.
    import pandas as pd

    scrambled_index = list(reversed(range(2, 2 + n_samples)))
    df_original_copy = pd.DataFrame(
        {"UITI_VANO": y.ravel()[::-1]}, index=scrambled_index
    )

    resultado = {
        "X": X,
        "y": y,
        "features": ["f0", "f1", "f2"],
        "df_original_copy": df_original_copy,
    }

    X_augmented, features_augmented = reinyectar_target_como_feature(
        resultado, nombre_target="UITI_VANO"
    )

    assert features_augmented == ["f0", "f1", "f2", "UITI_VANO"]
    assert X_augmented.shape == (n_samples, 4)
    np.testing.assert_array_equal(X_augmented[:, -1], y.ravel())
    np.testing.assert_array_equal(X_augmented[:, :3], X)


def test_reinjection_rejects_already_present_target() -> None:
    resultado = {
        "X": np.zeros((4, 2), dtype=np.float32),
        "y": np.zeros((4, 1), dtype=np.float32),
        "features": ["f0", "UITI_VANO"],
    }
    with pytest.raises(ValueError):
        reinyectar_target_como_feature(resultado, nombre_target="UITI_VANO")


# ---------------------------------------------------------------------------
# 1.7 / 1.9 -- PerSampleEdgeGateDecoder
# ---------------------------------------------------------------------------


def test_gate_decoder_zero_init_identity() -> None:
    edge_index = _tiny_edge_index()
    decoder = PerSampleEdgeGateDecoder(latent_dim=4, n_edges=edge_index.n_edges)

    for parameter in decoder.parameters():
        assert torch.equal(parameter, torch.zeros_like(parameter))

    z = torch.randn(8, 4)
    gates = decoder(z)
    assert torch.equal(gates, torch.ones_like(gates))


def test_gate_range_and_off_support_zero() -> None:
    gated = _tiny_gated_model(alpha=0.3)
    x = _tiny_batch()

    output = gated(x)
    gates = output["edge_gates"]
    assert torch.all(gates > 0.0) and torch.all(gates < 2.0)

    gated_adjacency = output["gated_adjacency"]
    p = len(_FEATURES)
    support_mask = torch.zeros((p, p), dtype=torch.bool)
    edge_rows = torch.as_tensor(_tiny_edge_index().pairs[:, 0])
    edge_cols = torch.as_tensor(_tiny_edge_index().pairs[:, 1])
    support_mask[edge_rows, edge_cols] = True
    off_support = gated_adjacency[:, ~support_mask]
    assert torch.equal(off_support, torch.zeros_like(off_support))


# ---------------------------------------------------------------------------
# 1.11 / 1.13 -- zero-init exactness and alpha=0 base-forward equivalence
# ---------------------------------------------------------------------------


def test_zero_init_exactness_A_hat_equals_A() -> None:
    gated = _tiny_gated_model(alpha=0.3)
    x = _tiny_batch()

    output = gated(x)
    adjacency = torch.as_tensor(_tiny_adjacency())
    for sample_index in range(x.shape[0]):
        assert torch.equal(output["gated_adjacency"][sample_index], adjacency)


def test_alpha_zero_recovers_base_forward_exactly() -> None:
    torch.manual_seed(7)
    base = _tiny_base_model(dropout=0.0)
    base.eval()
    gated = GraphGatedMGCECDLRegressor(
        base=base, adjacency=_tiny_adjacency(), edge_index=_tiny_edge_index(), alpha=0.0
    )
    gated.eval()

    x = _tiny_batch()
    gated_output = gated(x)
    assert torch.equal(gated_output["propagated_inputs"], x)

    with torch.no_grad():
        base_output = base(x)

    for key in ("fused_prediction", "reconstructed_features", "reliabilities"):
        assert torch.equal(gated_output[key], base_output[key])


# ---------------------------------------------------------------------------
# 1.15 -- reconstruction target is the ORIGINAL x (D2)
# ---------------------------------------------------------------------------


def test_reconstruction_target_is_original_x_not_propagated() -> None:
    gated = _tiny_gated_model(alpha=0.5)
    loss_fn = _tiny_loss()
    x = _tiny_batch()

    output = gated(x)
    against_original = loss_fn.compute_components(output, x)
    against_propagated = loss_fn.compute_components(output, output["propagated_inputs"])

    assert not torch.allclose(
        against_original["reconstruction_loss_raw"],
        against_propagated["reconstruction_loss_raw"],
    ), (
        "with alpha != 0 the propagated input differs from the original input, so scoring "
        "against each must give different reconstruction losses -- if they matched, the "
        "implementation likely defaulted to `propagated_inputs` somewhere"
    )


# ---------------------------------------------------------------------------
# 1.17 -- reconstruction_normalization="soft" is mandatory
# ---------------------------------------------------------------------------


def test_reconstruction_normalization_soft_required() -> None:
    n_features = len(_FEATURES)
    kwargs = dict(
        feature_mean=np.zeros(n_features, dtype=np.float32),
        feature_std=np.ones(n_features, dtype=np.float32),
        adjacency_matrix=_tiny_adjacency(),
    )

    with pytest.raises(ValueError):
        GatedSelfSupervisedLoss(**kwargs)  # default must NOT silently succeed

    with pytest.raises(ValueError):
        GatedSelfSupervisedLoss(reconstruction_normalization="clip", **kwargs)

    # Explicit "soft" must succeed.
    GatedSelfSupervisedLoss(reconstruction_normalization="soft", **kwargs)


# ---------------------------------------------------------------------------
# 1.19 -- gate-deviation loss is zero at g == 1 (fresh gate head)
# ---------------------------------------------------------------------------


def test_gate_deviation_loss_zero_at_g_equal_one() -> None:
    gated = _tiny_gated_model(alpha=0.3)
    loss_fn = _tiny_loss(lambda_gate_deviation=0.05)
    x = _tiny_batch()

    output = gated(x)
    components = loss_fn.compute_components(output, x)

    assert components["gate_deviation_loss"].item() == 0.0


# ---------------------------------------------------------------------------
# 1.21 / 1.23 -- gradient routing (D1): unused heads silent, gate head + shared
# encoder live.
# ---------------------------------------------------------------------------


def test_compute_components_never_takes_a_targets_argument() -> None:
    signature = inspect.signature(GatedSelfSupervisedLoss.compute_components)
    assert "targets" not in signature.parameters


def test_unused_heads_receive_no_gradient() -> None:
    gated = _tiny_gated_model(alpha=0.3)
    gated.train()
    loss_fn = _tiny_loss(lambda_gate_deviation=0.05)
    x = _tiny_batch()

    output = gated(x)
    components = loss_fn.compute_components(output, x)
    components["total_loss"].backward()

    for regressor in gated.base.modality_regressors:
        for parameter in regressor.parameters():
            assert parameter.grad is None

    for reliability_head in gated.base.modality_reliability_heads:
        for parameter in reliability_head.parameters():
            assert parameter.grad is None


def test_gradient_liveness_gate_head_and_shared_encoder() -> None:
    gated = _tiny_gated_model(alpha=0.3)
    gated.train()
    loss_fn = _tiny_loss(lambda_gate_deviation=0.05)
    x = _tiny_batch()

    output = gated(x)
    components = loss_fn.compute_components(output, x)
    components["total_loss"].backward()

    gate_grad = gated.gate_decoder.linear.weight.grad
    assert gate_grad is not None
    assert float(gate_grad.abs().sum()) > 0.0

    encoder_grad = gated.base.modality_encoders[0].network[0].weight.grad
    assert encoder_grad is not None
    assert float(encoder_grad.abs().sum()) > 0.0


# ---------------------------------------------------------------------------
# 1.25 -- batched Rényi entropy regression guard (read-only, no edit under
# `training/**`)
# ---------------------------------------------------------------------------


def test_batched_renyi_quadratic_entropy_rejects_or_routes_3d() -> None:
    from chec_impacto.training.mgcecdl import _renyi_quadratic_entropy

    # KEY MEASURED FACT: `.diagonal()` defaults to `dim1=0, dim2=1`, and both
    # `.sum()` and `.pow(2).sum()` are GLOBAL reductions -- on a 3-D
    # (batch, k, k) input this silently collapses to a single scalar instead
    # of raising or reducing per-sample. This locks in that CURRENT behavior
    # as a regression guard on edit-denied `training/mgcecdl.py:368-371`.
    batched_kernel = torch.rand(4, 3, 3)
    result = _renyi_quadratic_entropy(batched_kernel)

    assert result.ndim == 0, (
        "_renyi_quadratic_entropy silently collapses a 3-D kernel to a scalar instead of "
        "rejecting it or reducing per-sample -- see training/mgcecdl.py:368-371"
    )


def test_gated_pipeline_never_feeds_a_3d_kernel_into_renyi_entropy(monkeypatch) -> None:
    """Guard: our own gated forward/loss path must never trigger the bug above."""
    import chec_impacto.training.mgcecdl as training_mgcecdl

    observed_shapes: list[tuple[int, ...]] = []
    original = training_mgcecdl._renyi_quadratic_entropy

    def _spy(kernel, epsilon=1e-8):
        observed_shapes.append(tuple(kernel.shape))
        return original(kernel, epsilon)

    monkeypatch.setattr(training_mgcecdl, "_renyi_quadratic_entropy", _spy)

    gated = _tiny_gated_model(alpha=0.3)
    loss_fn = _tiny_loss(lambda_gate_deviation=0.05)
    x = _tiny_batch()

    output = gated(x)
    loss_fn.compute_components(output, x)

    assert observed_shapes, "expected _renyi_quadratic_entropy to be invoked at least once"
    assert all(len(shape) == 2 for shape in observed_shapes), (
        f"gated pipeline fed a non-2D kernel into _renyi_quadratic_entropy: {observed_shapes}"
    )


# ---------------------------------------------------------------------------
# 1.27 -- entrenar_gated_autoencoder smoke test
# ---------------------------------------------------------------------------


def test_entrenar_gated_autoencoder_smoke() -> None:
    torch.manual_seed(3)
    n_samples = 32
    X_past = np.random.default_rng(3).normal(size=(n_samples, len(_FEATURES))).astype(np.float32)

    gated = _tiny_gated_model(alpha=0.3)
    loss_fn = _tiny_loss(lambda_gate_deviation=0.01)

    result = entrenar_gated_autoencoder(
        gated,
        loss_fn,
        X_past,
        epochs=1,
        batch_size=8,
        lr=1e-3,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=3,
        device="cpu",
    )

    assert "reconstruction_loss_raw" in result
    assert np.isfinite(result["reconstruction_loss_raw"])
    assert "history" in result and len(result["history"]) == 1


def test_training_loop_scores_against_the_original_batch_not_the_propagated_one() -> None:
    # The design's central anti-gaming property: if the reconstruction were scored
    # against `propagated_inputs`, the gate could lower the loss by simplifying its
    # own target instead of by explaining the data. Asserting only that the loss
    # function *can* tell the two apart is nearly tautological for alpha != 0 -- the
    # invariant that matters is which tensor the TRAINING LOOP hands it, so capture
    # it directly.
    torch.manual_seed(3)
    n_samples = 32
    X_past = np.random.default_rng(3).normal(size=(n_samples, len(_FEATURES))).astype(np.float32)

    gated = _tiny_gated_model(alpha=0.5)
    loss_fn = _tiny_loss(lambda_gate_deviation=0.01)

    seen_inputs: list[torch.Tensor] = []
    original_compute_components = loss_fn.compute_components

    def spy(model_output, inputs):
        seen_inputs.append(inputs)
        return original_compute_components(model_output, inputs)

    loss_fn.compute_components = spy  # type: ignore[method-assign]
    entrenar_gated_autoencoder(
        gated,
        loss_fn,
        X_past,
        epochs=1,
        batch_size=8,
        lr=1e-3,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=3,
        device="cpu",
    )

    assert seen_inputs, "the training loop never called compute_components"

    # The loader shuffles (`shuffle=True`), so compare as an unordered multiset of
    # rows: over one epoch every original row must be scored exactly once. With
    # alpha != 0 the propagated batch differs from the original, so had the loop
    # passed `propagated_inputs` this would not be a permutation of X_past.
    def _rows_sorted(array: np.ndarray) -> np.ndarray:
        return array[np.lexsort(array.T[::-1])]

    observed = torch.cat(seen_inputs).cpu().numpy()
    expected = np.asarray(X_past, dtype=np.float32)

    assert observed.shape == expected.shape
    assert np.array_equal(_rows_sorted(observed), _rows_sorted(expected)), (
        "the training loop scored the reconstruction against tensors that are not the "
        "original batches -- it most likely passed model_output['propagated_inputs'], "
        "which lets the gate lower the loss by simplifying its own target"
    )
