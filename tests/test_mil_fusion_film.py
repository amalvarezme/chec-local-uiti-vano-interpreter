"""RED/GREEN tests for FiLM fusion: the arm that can represent interactions.

Measured motivation. Under `fusion="concat"` the bag prediction is
`w_est . z_est + w_clim . z_clim`. On a SINGLETON bag that is exactly
additive across modalities -- no structure x climate product exists at all
-- and 52.7% of the real bags hold exactly one event. On multi-instance
bags one weak coupling survives, and it is NOT the head: attention scores
are computed over the JOINT latent, so climate reweights how the structural
instances are pooled. Measured on the fixture, as a fraction of the p_bag
scale:

    concat, singleton bags : 2.7e-07   (float noise -- provably additive)
    concat, multi bags     : 6.6e-02   (attention-mediated only)
    film,   multi bags     : 1.7e-01

The graph is the other cross-modality path, and a thin one: 10 of its 64
edges (15.6%) cross modalities, scaled by `alpha` and multiplied by gates
whose measured ARI is 0.106.

RandomForest, which beats the model by 11-13 macro-F1 points on strictly
LESS information (30 structural bag-means, no climate), represents
interactions natively: every tree path is a conjunction across features.

FiLM lets climate MODULATE the structural representation:
`z = z_est * (1 + gamma(z_ctx)) + beta(z_ctx)`, on the POOLED embedding, so
unlike the attention channel it works at every bag size. The domain says the
same: a wind gust matters more on a tall, old, degraded pole.

The `test_concat_*` / `test_film_*` interaction trio measures the claim
rather than asserting it.
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
_CLIMA = [0, 1, 2]
_ESTRUCT = [3, 4, 5]
_MODALITIES = {"climaticos": _CLIMA, "estructurales": _ESTRUCT}
_INSTANCE_BAG = np.array([0, 0, 0, 1, 2, 2, 2, 2, 3, 3, 4, 4], dtype=np.int64)
_N_BAGS = 5
_EMBED = 4


def _adjacency() -> np.ndarray:
    pos = {n: i for i, n in enumerate(_FEATURES)}
    m = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for e in _EDGES:
        m[pos[e["source"]], pos[e["target"]]] = e["weight"]
    return m


def _model(fusion: str, **kwargs) -> MILBagRegressor:
    base = MGCECDLRegressor(
        modality_feature_indices=_MODALITIES, hidden_dim=16, embed_dim=_EMBED, dropout=0.0
    )
    return MILBagRegressor(
        base=base,
        adjacency=_adjacency(),
        edge_index=construir_edge_index(_adjacency(), _FEATURES, _EDGES),
        alpha=0.0,  # alpha=0 removes the graph's own cross-modality path
        attn_dim=8,
        fusion=fusion,
        **kwargs,
    ).eval()


def _film(**kwargs) -> MILBagRegressor:
    return _model("film", film_modulated_modality="estructurales", **kwargs)


def _bag() -> torch.Tensor:
    return torch.as_tensor(_INSTANCE_BAG)


_SINGLETON_BAG = torch.arange(6)  # every bag has exactly one instance


def _compose(x_clima: torch.Tensor, x_estruct: torch.Tensor) -> torch.Tensor:
    """Build an instance batch from independent per-modality halves."""
    x = torch.zeros(x_clima.shape[0], len(_FEATURES))
    x[:, _CLIMA] = x_clima
    x[:, _ESTRUCT] = x_estruct
    return x


def _half(seed: int, n: int = len(_INSTANCE_BAG)) -> torch.Tensor:
    g = torch.Generator().manual_seed(seed)
    return torch.randn(n, 3, generator=g)


def _p(model: MILBagRegressor, x: torch.Tensor) -> torch.Tensor:
    with torch.no_grad():
        return model(x, _bag(), _N_BAGS)["p_bag"]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_film_requires_naming_the_modulated_modality():
    """Which modality modulates which is a PHYSICAL claim; make it explicit."""
    with pytest.raises(ValueError, match="film_modulated_modality"):
        _model("film")


def test_film_rejects_an_unknown_modality_name():
    with pytest.raises(ValueError, match="no existe|desconocida"):
        _model("film", film_modulated_modality="inexistente")


def test_film_has_no_dead_concat_head():
    assert _film().head is None


# ---------------------------------------------------------------------------
# Identity at initialization
# ---------------------------------------------------------------------------


def test_film_starts_as_the_modulated_modality_alone():
    """gamma and beta are zero-init, so FiLM begins at `p = head(z_est)`.

    That is deliberate: the structural-only path is exactly what the winning
    RandomForest baseline uses, so training starts from it and adds
    modulation, instead of starting from noise.

    Checked on SINGLETON bags. With |bag| > 1 the attention weights are
    computed over the JOINT latent, so climate reshapes how the structural
    instances are pooled even when gamma == beta == 0 -- a real coupling,
    measured at ~6.6% of the p_bag scale, that has nothing to do with FiLM.
    """
    model = _film()
    assert torch.all(model.film_gamma.weight == 0)
    assert torch.all(model.film_gamma.bias == 0)
    assert torch.all(model.film_beta.weight == 0)
    assert torch.all(model.film_beta.bias == 0)

    # Climate cannot move the prediction while gamma == beta == 0.
    n = len(_SINGLETON_BAG)
    x_a = _compose(_half(1, n), _half(99, n))
    x_b = _compose(_half(2, n), _half(99, n))  # same structure, other climate
    with torch.no_grad():
        p_a = model(x_a, _SINGLETON_BAG, n)["p_bag"]
        p_b = model(x_b, _SINGLETON_BAG, n)["p_bag"]
    assert torch.allclose(p_a, p_b, atol=1e-6)


# ---------------------------------------------------------------------------
# The claim: concat cannot represent interactions, FiLM can.
# ---------------------------------------------------------------------------


def _interaccion(model: MILBagRegressor, bag: torch.Tensor | None = None):
    """2x2 design: p(A,1) - p(A,2) - p(B,1) + p(B,2), plus the p_bag scale.

    The 2x2 term is zero for any model additive across modalities.
    """
    bag = _bag() if bag is None else bag
    n = bag.shape[0]
    n_bags = int(bag.max()) + 1
    est_a, est_b = _half(11, n), _half(22, n)
    cli_1, cli_2 = _half(33, n), _half(44, n)

    def p(c, e):
        with torch.no_grad():
            return model(_compose(c, e), bag, n_bags)["p_bag"]

    termino = p(cli_1, est_a) - p(cli_2, est_a) - p(cli_1, est_b) + p(cli_2, est_b)
    escala = p(cli_1, est_a).abs().mean().clamp(min=1e-12)
    return termino, float(termino.abs().max() / escala)


def test_concat_is_exactly_additive_on_singleton_bags():
    """52.7% of the real bags are singletons -- for ALL of them, concat is
    provably additive across modalities, so no structure x climate
    interaction exists at all."""
    _, ratio = _interaccion(_model("concat"), _SINGLETON_BAG)
    assert ratio < 1e-5


def test_concat_interaction_on_multi_bags_is_only_attention_mediated():
    """Same model, same 2x2 design: additive on singletons, coupled on
    multi-instance bags. That isolates the mechanism -- attention scores are
    computed over the JOINT latent, so climate reweights how the structural
    instances are pooled. It is the model's ONLY interaction channel under
    concat, and it vanishes wherever a bag holds one event."""
    model = _model("concat")
    _, ratio_singleton = _interaccion(model, _SINGLETON_BAG)
    _, ratio_multi = _interaccion(model, _bag())
    assert ratio_singleton < 1e-5
    assert ratio_multi > 1e-3


def test_film_adds_interaction_even_on_singleton_bags():
    """The capacity concat does not have at all: FiLM modulates the POOLED
    embedding, so it works whatever the bag size."""
    model = _film()
    with torch.no_grad():
        model.film_gamma.weight.normal_(0.0, 0.5)
        model.film_beta.weight.normal_(0.0, 0.5)
    _, ratio = _interaccion(model, _SINGLETON_BAG)
    assert ratio > 1e-3


def test_film_fusion_is_not_additive_across_modalities():
    model = _film()
    with torch.no_grad():  # move off the zero-init identity
        model.film_gamma.weight.normal_(0.0, 0.5)
        model.film_beta.weight.normal_(0.0, 0.5)
    termino, _ = _interaccion(model)
    assert torch.any(termino.abs() > 1e-4)


def test_film_gradient_reaches_both_modality_encoders():
    model = _film()
    with torch.no_grad():
        model.film_gamma.weight.normal_(0.0, 0.5)
    x = _compose(_half(5), _half(6))
    model(x, _bag(), _N_BAGS)["p_bag"].sum().backward()

    for nombre, encoder in zip(
        model.base.modality_names, model.base.modality_encoders
    ):
        grads = [p.grad for p in encoder.parameters() if p.grad is not None]
        assert grads, f"el encoder de {nombre} no recibe gradiente"
        assert any(torch.any(g != 0) for g in grads), f"gradiente nulo en {nombre}"


def test_film_stays_cardinality_invariant():
    model = _film()
    with torch.no_grad():
        model.film_gamma.weight.normal_(0.0, 0.5)
    x = _compose(_half(7), _half(8))
    bag = _bag()

    x_dup = torch.cat([x, x], dim=0)
    bag_dup = torch.cat([bag, bag], dim=0)
    orden = torch.argsort(bag_dup, stable=True)

    with torch.no_grad():
        p1 = model(x, bag, _N_BAGS)["p_bag"]
        p2 = model(x_dup[orden], bag_dup[orden], _N_BAGS)["p_bag"]
    assert torch.allclose(p1, p2, atol=1e-5)


def test_film_exposes_its_modulation_for_inspection():
    """gamma/beta are the interpretable object: how climate rescaled structure."""
    model = _film()
    out = model(_compose(_half(3), _half(4)), _bag(), _N_BAGS)
    assert out["film_gamma"].shape == (_N_BAGS, _EMBED)
    assert out["film_beta"].shape == (_N_BAGS, _EMBED)
