"""Unit tests for the additive MGCECDL regression head (`MGCECDLRegressor`).

`MGCECDLRegressor` is a new, additive sibling of `MGCECDLClassifier`
(`src/chec_impacto/models/mgcecdl.py`) built for the VANO-level regression
exploration in `notebooks/project_flow/02.1_mgcecdl_regression_embeddings.ipynb`.
It reuses `_BaseMGCECDL`'s modality encoders/decoders/reliability heads and
replaces the per-modality classification heads with per-modality linear
regression heads, fusing predictions via the same reliability-weighted
mechanism `MGCECDLClassifier` uses for class probabilities -- but as a
weighted average of scalar predictions instead of a mixture of softmax
distributions.

`MGCECDLClassifier`'s existing behavior is untouched by this change.
"""

from __future__ import annotations

import torch

from chec_impacto.models import MGCECDLRegressor
from chec_impacto.models.mgcecdl import MGCECDLClassifier


def _modality_feature_indices() -> dict[str, list[int]]:
    return {"climaticos": [0, 1, 2], "estructurales": [3, 4]}


def _build_model(**overrides) -> MGCECDLRegressor:
    kwargs = dict(
        modality_feature_indices=_modality_feature_indices(),
        hidden_dim=16,
        embed_dim=8,
        dropout=0.0,
        temperature=1.0,
    )
    kwargs.update(overrides)
    return MGCECDLRegressor(**kwargs)


def test_forward_returns_expected_keys_and_shapes() -> None:
    torch.manual_seed(0)
    model = _build_model()
    x = torch.randn(4, 5)

    output = model(x)

    expected_keys = {
        "fused_prediction",
        "modality_predictions",
        "reliabilities",
        "embeddings",
        "modality_reconstructions",
        "reconstructed_features",
        "modality_names",
    }
    assert expected_keys.issubset(output.keys())
    assert output["fused_prediction"].shape == (4,)
    assert output["modality_predictions"].shape == (4, 2)
    assert output["reliabilities"].shape == (4, 2)
    assert len(output["embeddings"]) == 2
    for embedding in output["embeddings"]:
        assert embedding.shape == (4, 8)
    assert output["reconstructed_features"].shape == (4, 5)
    assert output["modality_names"] == ("climaticos", "estructurales")


def test_reliabilities_sum_to_one_per_sample() -> None:
    torch.manual_seed(1)
    model = _build_model()
    x = torch.randn(6, 5)

    output = model(x)

    row_sums = output["reliabilities"].sum(dim=1)
    assert torch.allclose(row_sums, torch.ones(6), atol=1e-5)


def test_fused_prediction_is_reliability_weighted_average_of_modality_predictions() -> None:
    torch.manual_seed(2)
    model = _build_model()
    x = torch.randn(3, 5)

    output = model(x)

    expected = (output["reliabilities"] * output["modality_predictions"]).sum(dim=1)
    assert torch.allclose(output["fused_prediction"], expected, atol=1e-6)


def test_masked_modality_gets_near_zero_reliability() -> None:
    torch.manual_seed(3)
    model = _build_model()
    x = torch.randn(2, 5)
    # Mask out the second modality ("estructurales") for every sample in the batch.
    modality_masks = torch.tensor([[1.0, 0.0], [1.0, 0.0]])

    output = model(x, modality_masks=modality_masks)

    assert torch.all(output["reliabilities"][:, 1] < 1e-4)
    assert torch.allclose(output["reliabilities"][:, 0], torch.ones(2), atol=1e-3)


def test_regressor_and_classifier_are_independent_siblings() -> None:
    """Adding MGCECDLRegressor must not alter MGCECDLClassifier's behavior."""
    torch.manual_seed(4)
    classifier = MGCECDLClassifier(
        modality_feature_indices=_modality_feature_indices(),
        n_classes=4,
        hidden_dim=16,
        embed_dim=8,
        dropout=0.0,
        temperature=1.0,
    )
    x = torch.randn(4, 5)
    classifier_output = classifier(x)

    assert classifier_output["fused_probs"].shape == (4, 4)
    assert not hasattr(classifier, "modality_regressors")

    regressor = _build_model()
    assert not hasattr(regressor, "modality_classifiers")
