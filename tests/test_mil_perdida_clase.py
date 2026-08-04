"""RED/GREEN tests for the class-aware loss term (differentiable through û).

The model trains on a density-weighted MSE over `log1p(u)` but is EVALUATED
on macro-F1 of a 4-class nearest-centroid map. Nothing in the loss knew
where the centroid boundaries were: a bag sitting on a boundary contributed
exactly like one deep inside its class.

`lambda_clase` closes that gap. It reuses 01.4's OWN frozen geometry -- the
same `Geometria` `asignar_clase` replays -- so the term optimizes the very
quantity `evaluar_arms` scores, and the target class is DERIVED from
`(n_obs, y_bag)` inside the loss rather than passed in, which makes an
inconsistent target impossible to supply.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from chec_impacto.models.criticality_assignment import (
    Geometria,
    _distancias_cuadradas,
    asignar_clase,
    distancias_cuadradas_torch,
)
from chec_impacto.models.mgcecdl import KernelDensityWeightedMSELoss, MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import construir_edge_index
from chec_impacto.models.mgcecdl_mil import MILBagLoss, MILBagRegressor

_FEATURES = ["a", "b", "c", "d", "e", "ind"]
_EDGES = [
    {"source": "a", "target": "b", "weight": 0.5},
    {"source": "b", "target": "c", "weight": 0.8},
    {"source": "c", "target": "d", "weight": 0.3},
    {"source": "d", "target": "e", "weight": 0.6},
]
_MODALITIES = {"climaticos": [0, 1, 2], "estructurales": [3, 4, 5]}
_INSTANCE_BAG = np.array([0, 0, 0, 1, 2, 2, 2, 2, 3, 3, 4, 4], dtype=np.int64)
_N_BAGS = 5


def _geometria() -> Geometria:
    """Mirrors 01.4's canonical space: axis 0 = n_obs (raw), axis 1 = u (log10)."""
    return Geometria(
        logs=(False, True),
        offset=np.array([1.0, -3.0], dtype=np.float64),
        scale=np.array([45.0, 7.424386], dtype=np.float64),
        centroides=np.array(
            [[0.00, 0.55], [0.02, 0.65], [0.04, 0.75], [0.06, 0.88]], dtype=np.float64
        ),
    )


def _adjacency() -> np.ndarray:
    pos = {n: i for i, n in enumerate(_FEATURES)}
    m = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for e in _EDGES:
        m[pos[e["source"]], pos[e["target"]]] = e["weight"]
    return m


def _model(fusion: str = "concat") -> MILBagRegressor:
    base = MGCECDLRegressor(
        modality_feature_indices=_MODALITIES, hidden_dim=16, embed_dim=4, dropout=0.0
    )
    return MILBagRegressor(
        base=base,
        adjacency=_adjacency(),
        edge_index=construir_edge_index(_adjacency(), _FEATURES, _EDGES),
        alpha=0.3,
        attn_dim=8,
        fusion=fusion,
    )


def _loss_kwargs(**overrides):
    p = len(_FEATURES)
    base = dict(
        feature_mean=np.zeros(p, dtype=np.float32),
        feature_std=np.ones(p, dtype=np.float32),
        adjacency_matrix=_adjacency(),
        kernel_loss=KernelDensityWeightedMSELoss.from_targets(
            np.log1p(np.linspace(0.5, 20.0, 32))
        ),
        lambda_reconstruction=0.01,
        lambda_mutual_information=0.01,
        reconstruction_normalization="soft",
    )
    base.update(overrides)
    return base


def _batch(seed: int = 0) -> torch.Tensor:
    g = torch.Generator().manual_seed(seed)
    return torch.randn(len(_INSTANCE_BAG), len(_FEATURES), generator=g)


def _y_bag() -> torch.Tensor:
    return torch.tensor([2.0, 40.0, 300.0, 9000.0, 150.0])


def _n_obs() -> torch.Tensor:
    return torch.tensor([3.0, 1.0, 4.0, 2.0, 2.0])


# ---------------------------------------------------------------------------
# The torch geometry must agree with the numpy one it mirrors.
# ---------------------------------------------------------------------------


def test_torch_distances_match_the_numpy_implementation():
    geo = _geometria()
    n_obs = np.array([1.0, 2.0, 5.0, 12.0, 46.0])
    u = np.array([0.5, 12.0, 900.0, 5e4, 3.0])

    esperado, _ = _distancias_cuadradas(n_obs, u, geo, 1e-6)
    obtenido = distancias_cuadradas_torch(
        torch.as_tensor(n_obs), torch.as_tensor(u), geo
    )
    assert torch.allclose(obtenido.double(), torch.as_tensor(esperado), atol=1e-9)


def test_torch_distances_reproduce_the_hard_class_assignment():
    geo = _geometria()
    n_obs = np.array([1.0, 2.0, 5.0, 12.0, 46.0])
    u = np.array([0.5, 12.0, 900.0, 5e4, 3.0])

    clase_np, _ = asignar_clase(n_obs, u, geo)
    clase_torch = distancias_cuadradas_torch(
        torch.as_tensor(n_obs), torch.as_tensor(u), geo
    ).argmin(dim=-1)
    assert np.array_equal(clase_np, clase_torch.numpy())


def test_torch_distances_are_differentiable_in_u():
    geo = _geometria()
    u = torch.tensor([5.0, 100.0, 2000.0], requires_grad=True)
    n_obs = torch.tensor([1.0, 2.0, 3.0])
    distancias_cuadradas_torch(n_obs, u, geo).sum().backward()
    assert u.grad is not None and torch.any(u.grad != 0)


def test_torch_distances_clamp_non_positive_u_without_nan():
    geo = _geometria()
    u = torch.tensor([0.0, -5.0, 10.0], requires_grad=True)
    d2 = distancias_cuadradas_torch(torch.tensor([1.0, 1.0, 1.0]), u, geo)
    assert torch.isfinite(d2).all()
    d2.sum().backward()
    assert torch.isfinite(u.grad).all()


# ---------------------------------------------------------------------------
# The loss term.
# ---------------------------------------------------------------------------


def test_class_term_defaults_to_off():
    model, x = _model(), _batch()
    out = model(x, torch.as_tensor(_INSTANCE_BAG), _N_BAGS)
    comp = MILBagLoss(**_loss_kwargs()).compute_components(out, x, _y_bag())
    assert float(comp["class_loss"]) == 0.0


def test_class_term_requires_a_geometry_when_enabled():
    with pytest.raises(ValueError, match="geometria"):
        MILBagLoss(**_loss_kwargs(lambda_clase=0.5))


def test_class_term_requires_n_obs_at_call_time():
    """Silent inertness is what let the SHAP annotation bug survive."""
    model, x = _model(), _batch()
    out = model(x, torch.as_tensor(_INSTANCE_BAG), _N_BAGS)
    perdida = MILBagLoss(**_loss_kwargs(lambda_clase=0.5, geometria=_geometria()))
    with pytest.raises(ValueError, match="n_obs"):
        perdida.compute_components(out, x, _y_bag())


def test_class_term_adds_a_positive_component():
    model, x = _model(), _batch()
    out = model(x, torch.as_tensor(_INSTANCE_BAG), _N_BAGS)

    apagado = MILBagLoss(**_loss_kwargs()).compute_components(out, x, _y_bag())
    encendido = MILBagLoss(
        **_loss_kwargs(lambda_clase=0.5, geometria=_geometria())
    ).compute_components(out, x, _y_bag(), n_obs=_n_obs())

    assert float(encendido["class_loss"]) > 0.0
    assert float(encendido["total_loss"]) > float(apagado["total_loss"])
    assert torch.allclose(encendido["supervised_loss"], apagado["supervised_loss"])


def test_class_term_rewards_a_prediction_that_lands_on_the_right_class():
    """The behavioural claim: a perfect û must score better than a wrong one."""
    geo, y, n_obs = _geometria(), _y_bag(), _n_obs()
    perdida = MILBagLoss(**_loss_kwargs(lambda_clase=1.0, geometria=geo))

    perfecto = {"p_bag": torch.log1p(y)}
    psimo = {"p_bag": torch.full_like(y, 0.01)}

    ce_perfecto = perdida._perdida_de_clase(perfecto["p_bag"], y, n_obs)
    ce_psimo = perdida._perdida_de_clase(psimo["p_bag"], y, n_obs)
    assert float(ce_perfecto) < float(ce_psimo)


def test_class_term_sends_gradient_back_through_p_bag():
    model, x = _model(), _batch()
    out = model(x, torch.as_tensor(_INSTANCE_BAG), _N_BAGS)
    perdida = MILBagLoss(**_loss_kwargs(lambda_clase=1.0, geometria=_geometria()))
    perdida.compute_components(out, x, _y_bag(), n_obs=_n_obs())["class_loss"].backward()

    grads = [p.grad for p in model.parameters() if p.grad is not None]
    assert grads, "el termino de clase no propago gradiente al modelo"
    assert any(torch.any(g != 0) for g in grads)


def test_softplus_floor_does_not_distort_the_realistic_u_range():
    """The floor must be invisible where the centroids actually live.

    `offset[1] = -3.0`, `scale[1] = 7.424386` and centroid z1 in [0.55, 0.88]
    put the modelled band at u in roughly [12, 3400]; softplus must equal u
    to float precision across it, or the term would bias predictions.
    """
    import torch.nn.functional as F

    u = torch.tensor([12.0, 100.0, 1000.0, 3400.0], dtype=torch.float64)
    assert torch.allclose(F.softplus(u), u, rtol=0, atol=1e-5)


def test_class_term_has_non_zero_gradient_at_initialization():
    """The regression this pins: a hard clamp made the term inert at p_bag ~ 0."""
    geo = _geometria()
    perdida = MILBagLoss(**_loss_kwargs(lambda_clase=1.0, geometria=geo))
    p_bag = torch.zeros(5, requires_grad=True)  # exactly the init regime
    perdida._perdida_de_clase(p_bag, _y_bag(), _n_obs()).backward()
    assert p_bag.grad is not None and torch.any(p_bag.grad != 0)


# ---------------------------------------------------------------------------
# Temperature: the parameter that decides whether the term can learn at all.
# ---------------------------------------------------------------------------

_ENTROPIA_UNIFORME_4 = float(np.log(4.0))  # 1.3863


def test_default_temperature_yields_a_usable_gradient_signal():
    """The regression this pins, measured on the real geometry.

    `distribucion_suave` defaults to `temperatura=1.0`, which is correct for
    what it documents: softmax is strictly monotone in -d^2, so ANY T > 0
    gives the same argmax for SHAP and the simulator. That same property is
    what makes T critical for a cross-entropy: it sets how peaked the
    distribution is, and nothing else.

    On 01.4's real geometry the squared distances to the 4 centroids have
    median 0.038 and the gap between nearest and runner-up is 0.017. Divided
    by T=1.0 those logits differ by ~0.02, so the softmax comes out 99.9%
    uniform: the measured entropy was 1.3850 against ln(4) = 1.3863, and the
    term sat at ~1.35 from epoch 1 to epoch 6 -- already at its own floor,
    contributing a constant and no gradient.

    So the assertion is not "T equals some number" but "a PERFECT prediction
    must score far better than chance", which is the property the term needs
    in order to teach anything.
    """
    geo = _geometria()
    perdida = MILBagLoss(**_loss_kwargs(lambda_clase=1.0, geometria=geo))

    y, n_obs = _y_bag(), _n_obs()
    ce_perfecta = float(perdida._perdida_de_clase(torch.log1p(y), y, n_obs))

    assert ce_perfecta < 0.5 * _ENTROPIA_UNIFORME_4, (
        f"con una prediccion perfecta la CE es {ce_perfecta:.4f}, contra "
        f"{_ENTROPIA_UNIFORME_4:.4f} de una distribucion uniforme: la temperatura "
        "aplana la softmax y el termino no puede aprender."
    )


def test_temperature_of_one_is_what_flattened_the_term():
    """Documents the failure directly, so the fix cannot silently regress."""
    geo = _geometria()
    y, n_obs = _y_bag(), _n_obs()
    plana = MILBagLoss(**_loss_kwargs(lambda_clase=1.0, geometria=geo, temperatura_clase=1.0))
    ce = float(plana._perdida_de_clase(torch.log1p(y), y, n_obs))
    assert ce > 0.9 * _ENTROPIA_UNIFORME_4, "T=1.0 deberia dar una softmax casi uniforme"


def test_temperature_is_tunable_and_lower_means_sharper():
    geo = _geometria()
    y, n_obs = _y_bag(), _n_obs()

    def ce(t):
        return float(
            MILBagLoss(
                **_loss_kwargs(lambda_clase=1.0, geometria=geo, temperatura_clase=t)
            )._perdida_de_clase(torch.log1p(y), y, n_obs)
        )

    assert ce(1.0) > ce(0.1) > ce(0.01) > ce(0.003)
