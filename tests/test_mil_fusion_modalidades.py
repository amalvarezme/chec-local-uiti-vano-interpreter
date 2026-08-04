"""RED/GREEN tests for bag-grain reliability fusion in `MILBagRegressor`.

`MGCECDLRegressor.forward` fuses per-modality predictions at INSTANCE grain,
weighted by per-modality reliabilities. `MILBagRegressor` could not use that
path: the label is per BAG, so an instance-grain fused prediction has no
target. It therefore read only `embeddings`/`reconstructed_features` and
predicted through a single `Linear(latent_dim, 1)` over the concatenated
pooled latent -- which left `base.modality_regressors` and
`base.modality_reliability_heads` with zero gradient.

`fusion="reliability"` moves the fusion to bag grain, which is where the
label lives. It costs no extra pooling: pooling is linear in `z` for fixed
attention weights, so the per-modality pooled embedding is exactly the
corresponding column slice of the concatenated pooled latent -- pinned by
`test_pooled_modality_slice_equals_separately_pooled_modality`.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from chec_impacto.models.mgcecdl import MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import construir_edge_index
from chec_impacto.models.mgcecdl_mil import MILBagRegressor

_FEATURES = ["a", "b", "c", "d", "e", "ind"]
_EDGES = [
    {"source": "a", "target": "b", "weight": 0.5},
    {"source": "b", "target": "c", "weight": 0.8},
    {"source": "c", "target": "d", "weight": 0.3},
    {"source": "d", "target": "e", "weight": 0.6},
]
_MODALITY_FEATURE_INDICES = {"climaticos": [0, 1, 2], "estructurales": [3, 4, 5]}
_INSTANCE_BAG = np.array([0, 0, 0, 1, 2, 2, 2, 2, 3, 3, 4, 4], dtype=np.int64)
_N_BAGS = 5
_EMBED_DIM = 4


def _adjacency() -> np.ndarray:
    pos = {n: i for i, n in enumerate(_FEATURES)}
    m = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for e in _EDGES:
        m[pos[e["source"]], pos[e["target"]]] = e["weight"]
    return m


def _model(fusion: str = "concat", alpha: float = 0.3) -> MILBagRegressor:
    base = MGCECDLRegressor(
        modality_feature_indices=_MODALITY_FEATURE_INDICES,
        hidden_dim=16,
        embed_dim=_EMBED_DIM,
        dropout=0.0,
        temperature=1.0,
    )
    return MILBagRegressor(
        base=base,
        adjacency=_adjacency(),
        edge_index=construir_edge_index(_adjacency(), _FEATURES, _EDGES),
        alpha=alpha,
        attn_dim=8,
        fusion=fusion,
    )


def _batch(seed: int = 0, n_inst: int = len(_INSTANCE_BAG)) -> torch.Tensor:
    g = torch.Generator().manual_seed(seed)
    return torch.randn(n_inst, len(_FEATURES), generator=g)


def _bag_tensor() -> torch.Tensor:
    return torch.as_tensor(_INSTANCE_BAG)


# ---------------------------------------------------------------------------
# The defect: the per-modality heads receive no gradient under "concat".
# ---------------------------------------------------------------------------


def test_concat_fusion_leaves_modality_heads_without_gradient():
    """Documents the CURRENT default -- this is the behaviour being fixed."""
    model = _model(fusion="concat")
    out = model(_batch(), _bag_tensor(), _N_BAGS)
    out["p_bag"].sum().backward()

    for head in model.base.modality_regressors:
        assert head.weight.grad is None or torch.all(head.weight.grad == 0)
    for head in model.base.modality_reliability_heads:
        assert head.weight.grad is None or torch.all(head.weight.grad == 0)


def test_reliability_fusion_sends_gradient_to_both_modality_head_families():
    """The fix: both dead ModuleLists must receive NON-ZERO gradient."""
    model = _model(fusion="reliability")
    out = model(_batch(), _bag_tensor(), _N_BAGS)
    out["p_bag"].sum().backward()

    for i, head in enumerate(model.base.modality_regressors):
        assert head.weight.grad is not None, f"modality_regressors[{i}] still dead"
        assert torch.any(head.weight.grad != 0), f"modality_regressors[{i}] has all-zero grad"
    for i, head in enumerate(model.base.modality_reliability_heads):
        assert head.weight.grad is not None, f"modality_reliability_heads[{i}] still dead"
        assert torch.any(head.weight.grad != 0), (
            f"modality_reliability_heads[{i}] has all-zero grad"
        )


def test_reliability_fusion_exposes_bag_grain_reliabilities_and_predictions():
    model = _model(fusion="reliability")
    out = model(_batch(), _bag_tensor(), _N_BAGS)

    n_mod = model.base.n_modalities
    assert out["reliabilities"].shape == (_N_BAGS, n_mod)
    assert out["modality_predictions"].shape == (_N_BAGS, n_mod)
    assert torch.allclose(
        out["reliabilities"].sum(dim=1), torch.ones(_N_BAGS), atol=1e-6
    )
    assert torch.all(out["reliabilities"] >= 0)


def test_reliability_fusion_p_bag_is_exactly_the_weighted_sum():
    model = _model(fusion="reliability")
    out = model(_batch(), _bag_tensor(), _N_BAGS)
    esperado = (out["reliabilities"] * out["modality_predictions"]).sum(dim=1)
    assert torch.allclose(out["p_bag"], esperado, atol=1e-6)


def test_concat_fusion_does_not_expose_reliabilities():
    """The concat arm must stay exactly what it was -- no phantom keys."""
    out = _model(fusion="concat")(_batch(), _bag_tensor(), _N_BAGS)
    assert "reliabilities" not in out
    assert "modality_predictions" not in out


def test_pooled_modality_slice_equals_separately_pooled_modality():
    """Why bag-grain fusion is free: pooling is linear in z for fixed a."""
    model = _model(fusion="reliability")
    x = _batch()
    bag = _bag_tensor()
    out = model(x, bag, _N_BAGS)

    # Re-pool modality 0 on its own, using the SAME attention weights.
    z2 = torch.cat(out["embeddings"], dim=1)
    _, attention = model.attention_pool(z2, bag, _N_BAGS)
    z_mod0 = out["embeddings"][0]
    pooled_mod0 = z_mod0.new_zeros((_N_BAGS, z_mod0.shape[1])).index_add(
        0, bag, attention.unsqueeze(-1) * z_mod0
    )

    z_bag_2 = z2.new_zeros((_N_BAGS, z2.shape[1])).index_add(
        0, bag, attention.unsqueeze(-1) * z2
    )
    assert torch.allclose(z_bag_2[:, :_EMBED_DIM], pooled_mod0, atol=1e-6)


def test_reliability_fusion_stays_cardinality_invariant():
    """Duplicating every instance of every bag must not move p_bag."""
    model = _model(fusion="reliability").eval()
    x = _batch()
    bag = _bag_tensor()

    x_dup = torch.cat([x, x], dim=0)
    bag_dup = torch.cat([bag, bag], dim=0)
    orden = torch.argsort(bag_dup, stable=True)

    with torch.no_grad():
        p1 = model(x, bag, _N_BAGS)["p_bag"]
        p2 = model(x_dup[orden], bag_dup[orden], _N_BAGS)["p_bag"]
    assert torch.allclose(p1, p2, atol=1e-5)


def test_unknown_fusion_mode_is_rejected():
    with pytest.raises(ValueError, match="fusion"):
        _model(fusion="promedio")


def test_reliability_fusion_has_no_dead_concat_head():
    """Replacing one dead path with another would defeat the point."""
    model = _model(fusion="reliability")
    assert not hasattr(model, "head") or model.head is None


# ---------------------------------------------------------------------------
# Per-modality supervision: what makes the reliabilities readable.
# ---------------------------------------------------------------------------


def _loss_kwargs(**overrides):
    from chec_impacto.models.mgcecdl import KernelDensityWeightedMSELoss

    p = len(_FEATURES)
    y_train = np.linspace(0.5, 20.0, 32)
    base = dict(
        feature_mean=np.zeros(p, dtype=np.float32),
        feature_std=np.ones(p, dtype=np.float32),
        adjacency_matrix=_adjacency(),
        kernel_loss=KernelDensityWeightedMSELoss.from_targets(np.log1p(y_train)),
        lambda_reconstruction=0.01,
        lambda_mutual_information=0.01,
        lambda_gate_deviation=0.0,
        reconstruction_normalization="soft",
    )
    base.update(overrides)
    return base


def _y_bag() -> torch.Tensor:
    return torch.linspace(0.5, 9.0, _N_BAGS)


def test_modality_supervision_defaults_to_off():
    from chec_impacto.models.mgcecdl_mil import MILBagLoss

    model = _model(fusion="reliability")
    x = _batch()
    out = model(x, _bag_tensor(), _N_BAGS)

    perdida = MILBagLoss(**_loss_kwargs())
    componentes = perdida.compute_components(out, x, _y_bag())
    assert float(componentes["modality_supervised_loss"]) == 0.0


def test_modality_supervision_adds_a_positive_term_when_enabled():
    from chec_impacto.models.mgcecdl_mil import MILBagLoss

    model = _model(fusion="reliability")
    x = _batch()
    out = model(x, _bag_tensor(), _N_BAGS)

    apagada = MILBagLoss(**_loss_kwargs()).compute_components(out, x, _y_bag())
    encendida = MILBagLoss(
        **_loss_kwargs(lambda_modality_supervised=0.5)
    ).compute_components(out, x, _y_bag())

    assert float(encendida["modality_supervised_loss"]) > 0.0
    assert float(encendida["total_loss"]) > float(apagada["total_loss"])
    # el termino supervisado de la bolsa no debe cambiar
    assert torch.allclose(encendida["supervised_loss"], apagada["supervised_loss"])


def test_modality_supervision_is_inert_without_reliability_fusion():
    """Under "concat" there are no per-modality predictions to supervise."""
    from chec_impacto.models.mgcecdl_mil import MILBagLoss

    model = _model(fusion="concat")
    x = _batch()
    out = model(x, _bag_tensor(), _N_BAGS)

    componentes = MILBagLoss(
        **_loss_kwargs(lambda_modality_supervised=0.5)
    ).compute_components(out, x, _y_bag())
    assert float(componentes["modality_supervised_loss"]) == 0.0


def test_modality_supervision_reaches_each_modality_regressor():
    from chec_impacto.models.mgcecdl_mil import MILBagLoss

    model = _model(fusion="reliability")
    x = _batch()
    out = model(x, _bag_tensor(), _N_BAGS)
    perdida = MILBagLoss(**_loss_kwargs(lambda_modality_supervised=1.0))
    perdida.compute_components(out, x, _y_bag())["modality_supervised_loss"].backward()

    for i, head in enumerate(model.base.modality_regressors):
        assert head.weight.grad is not None and torch.any(head.weight.grad != 0), (
            f"modality_regressors[{i}] no recibe gradiente del termino por modalidad"
        )
