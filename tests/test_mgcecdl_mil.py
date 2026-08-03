"""RED/GREEN tests for the bag-level MIL regressor
(`src/chec_impacto/models/mgcecdl_mil.py`).

Covers `SegmentAttentionPool` (cardinality invariance, normalization),
`MILBagRegressor` (per-bag gate topology, zero-init identity, alpha=0
equivalence, off-support propagation, dead-head gradient isolation),
`MILBagLoss` (loss composition, reconstruction target fixity, fold
hygiene), and `entrenar_mil` (fit loop). See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain `mil-bag-model`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D2, D3, D5)

All fixtures are a tiny synthetic bag layout: `n_inst=12`, `n_bags=5`,
`p=6` features (one of which, `"ind"`, has zero graph edges -- it stands
in for a degree-0 `COD_CAUSA_*` indicator column), `E=4` edges. Dimensions
are read from the fixture data itself everywhere, never hardcoded as
literals in the module under test (see
`test_no_forbidden_literal_counts_in_mil_module`).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from chec_impacto.data.bags import BagIndex
from chec_impacto.models.mgcecdl import KernelDensityWeightedMSELoss, MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import construir_edge_index
from chec_impacto.models.mgcecdl_mil import (
    MILBagLoss,
    MILBagRegressor,
    SegmentAttentionPool,
    entrenar_mil,
)

MIL_MODULE_PATH = Path("src/chec_impacto/models/mgcecdl_mil.py")

# ---------------------------------------------------------------------------
# Tiny synthetic bag fixture -- n_inst=12, n_bags=5, p=6, E=4.
# ---------------------------------------------------------------------------

_FEATURES = ["a", "b", "c", "d", "e", "ind"]  # "ind": degree-0, mirrors COD_CAUSA_* indicators
_EDGES = [
    {"source": "a", "target": "b", "weight": 0.5},
    {"source": "b", "target": "c", "weight": 0.8},
    {"source": "c", "target": "d", "weight": 0.3},
    {"source": "d", "target": "e", "weight": 0.6},
]
_MODALITY_FEATURE_INDICES = {"climaticos": [0, 1, 2], "estructurales": [3, 4, 5]}
_INSTANCE_BAG = np.array([0, 0, 0, 1, 2, 2, 2, 2, 3, 3, 4, 4], dtype=np.int64)  # counts [3,1,4,2,2]
_N_BAGS = 5
_N_INST = len(_INSTANCE_BAG)


def _tiny_adjacency() -> np.ndarray:
    positions = {name: index for index, name in enumerate(_FEATURES)}
    matrix = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for edge in _EDGES:
        matrix[positions[edge["source"]], positions[edge["target"]]] = edge["weight"]
    return matrix


def _tiny_edge_index():
    return construir_edge_index(_tiny_adjacency(), _FEATURES, _EDGES)


def _tiny_base_model(dropout: float = 0.0) -> MGCECDLRegressor:
    return MGCECDLRegressor(
        modality_feature_indices=_MODALITY_FEATURE_INDICES,
        hidden_dim=16,
        embed_dim=4,
        dropout=dropout,
        temperature=1.0,
    )


def _tiny_mil_model(alpha: float = 0.3, dropout: float = 0.0, attn_dim: int = 8) -> MILBagRegressor:
    base = _tiny_base_model(dropout=dropout)
    return MILBagRegressor(
        base=base,
        adjacency=_tiny_adjacency(),
        edge_index=_tiny_edge_index(),
        alpha=alpha,
        attn_dim=attn_dim,
    )


def _tiny_instance_batch(n_inst: int = _N_INST, seed: int = 0) -> torch.Tensor:
    generator = torch.Generator().manual_seed(seed)
    return torch.randn(n_inst, len(_FEATURES), generator=generator)


def _tiny_loss_kwargs() -> dict:
    n_features = len(_FEATURES)
    y_train = np.linspace(0.5, 20.0, 32)
    return dict(
        feature_mean=np.zeros(n_features, dtype=np.float32),
        feature_std=np.ones(n_features, dtype=np.float32),
        adjacency_matrix=_tiny_adjacency(),
        kernel_loss=KernelDensityWeightedMSELoss.from_targets(np.log1p(y_train)),
    )


def _tiny_loss(lambda_gate_deviation: float = 0.0) -> MILBagLoss:
    return MILBagLoss(lambda_gate_deviation=lambda_gate_deviation, **_tiny_loss_kwargs())


def _bag_index_sintetica_de_prueba() -> BagIndex:
    counts = np.array([3, 1, 4, 2, 2], dtype=np.int64)
    offsets = np.zeros(_N_BAGS + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(counts)
    keys = pd.DataFrame(
        {
            "CIRCUITO": [f"C{i}" for i in range(_N_BAGS)],
            "FID_VANO": [f"V{i}" for i in range(_N_BAGS)],
            "VENTANA": ["W1"] * _N_BAGS,
        }
    )
    group = np.array([f"C{i}|V{i}" for i in range(_N_BAGS)], dtype=object)
    y = np.array([1.5, 4.0, 0.8, 12.0, 3.3], dtype=np.float64)
    return BagIndex(
        keys=keys,
        instance_bag=_INSTANCE_BAG,
        offsets=offsets,
        counts=counts,
        y=y,
        group=group,
        instance_rows=np.arange(_N_INST, dtype=np.int64),
    )


# ---------------------------------------------------------------------------
# 3.1 / 3.3 -- SegmentAttentionPool
# ---------------------------------------------------------------------------


def test_segment_attention_pool_cardinality_invariance_A2() -> None:
    """Duplicating every instance of every bag must leave `z_bag` unchanged
    (design D2's central correctness claim, not a hyperparameter)."""
    torch.manual_seed(0)
    latent_dim = 8
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)
    z = torch.randn(_N_INST, latent_dim)

    pool = SegmentAttentionPool(latent_dim=latent_dim, attn_dim=6)
    pool.eval()  # Dropout is the only stochastic layer anywhere in this design (D2).

    z_bag_original, _ = pool(z, instance_bag, _N_BAGS)

    z_duplicated = torch.cat([z, z], dim=0)
    instance_bag_duplicated = torch.cat([instance_bag, instance_bag], dim=0)
    z_bag_duplicated, _ = pool(z_duplicated, instance_bag_duplicated, _N_BAGS)

    assert torch.allclose(z_bag_original, z_bag_duplicated, atol=1e-6)
    assert not torch.allclose(z_bag_original, torch.zeros_like(z_bag_original)), (
        "the fixture must produce a non-trivial pooled latent, else the invariance check is vacuous"
    )


def test_segment_attention_weights_sum_to_one_per_bag() -> None:
    torch.manual_seed(1)
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)
    z = torch.randn(_N_INST, 8)
    pool = SegmentAttentionPool(latent_dim=8, attn_dim=6)

    _, attention = pool(z, instance_bag, _N_BAGS)

    sums = torch.zeros(_N_BAGS)
    sums.index_add_(0, instance_bag, attention)
    torch.testing.assert_close(sums, torch.ones(_N_BAGS))


# ---------------------------------------------------------------------------
# 3.4 -- g == 1 and A_hat == A at init (zero-init gate decoder)
# ---------------------------------------------------------------------------


def test_gate_decoder_zero_init_g_equal_one_and_matches_dense_A() -> None:
    model = _tiny_mil_model(alpha=1.0)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)

    output = model(x, instance_bag, _N_BAGS)
    assert torch.equal(output["edge_gates"], torch.ones_like(output["edge_gates"]))

    # A_hat == A at init: the edge-wise (index_add) propagation must match a dense
    # X @ A reference exactly when every gate is 1.
    adjacency = torch.as_tensor(_tiny_adjacency())
    dense_expected = x + model.alpha * torch.matmul(x, adjacency)
    assert torch.allclose(output["propagated_inputs"], dense_expected, atol=1e-5)


# ---------------------------------------------------------------------------
# 3.5 -- alpha == 0 reproduces the ungated bag forward exactly
# ---------------------------------------------------------------------------


def test_alpha_zero_recovers_propagated_inputs_exactly() -> None:
    model = _tiny_mil_model(alpha=0.0)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)

    output = model(x, instance_bag, _N_BAGS)
    assert torch.equal(output["propagated_inputs"], x)


# ---------------------------------------------------------------------------
# 3.6 -- off-support columns (incl. every degree-0 indicator) stay unchanged
# ---------------------------------------------------------------------------


def test_off_support_columns_stay_unchanged_after_propagation() -> None:
    model = _tiny_mil_model(alpha=0.7)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)

    output = model(x, instance_bag, _N_BAGS)
    propagated = output["propagated_inputs"]

    edge_cols = set(_tiny_edge_index().pairs[:, 1].tolist())
    off_support_positions = [i for i in range(len(_FEATURES)) if i not in edge_cols]
    assert off_support_positions, (
        "fixture must include at least one degree-0 column (mirrors COD_CAUSA_* indicators)"
    )
    assert _FEATURES.index("ind") in off_support_positions

    for position in off_support_positions:
        assert torch.equal(propagated[:, position], x[:, position])


# ---------------------------------------------------------------------------
# 3.7 -- forward output shape / grouping sanity (GREEN triangulation)
# ---------------------------------------------------------------------------


def test_forward_produces_one_gate_vector_and_one_prediction_per_bag() -> None:
    model = _tiny_mil_model(alpha=0.3)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)

    output = model(x, instance_bag, _N_BAGS)

    assert output["p_bag"].shape == (_N_BAGS,)
    assert output["edge_gates"].shape == (_N_BAGS, _tiny_edge_index().n_edges)
    assert output["attention"].shape == (_N_INST,)
    assert output["reconstructed_features"].shape == (_N_INST, len(_FEATURES))
    assert output["propagated_inputs"].shape == (_N_INST, len(_FEATURES))


def test_no_forbidden_literal_counts_in_mil_module() -> None:
    """No literal feature/edge/COD_CAUSA-cardinality count may appear in the
    MIL module's source -- see obs #536: the real dataset yields `p=80`,
    `E=64`, not the design's earlier `p ~= 81-85` estimate, so this module
    must always derive both at runtime from the caller-supplied
    adjacency/edge index, never hardcode either.

    `64` is excluded from the forbidden set: it is `attn_dim`'s legitimate
    default (design's Interfaces contract pins `attn_dim: int = 64`), an
    attention-projection width that has nothing to do with the feature/edge
    topology obs #536 is about -- forbidding it would false-positive on a
    real, intentional hyperparameter rather than catch a hardcoded `p`/`E`.
    """
    source = MIL_MODULE_PATH.read_text(encoding="utf-8")
    forbidden_pattern = re.compile(r"\b(?:56|70|71|73|74|75|80|81|84|85)\b")
    matches = forbidden_pattern.findall(source)
    assert not matches, f"forbidden literal count(s) found in {MIL_MODULE_PATH}: {matches}"


# ---------------------------------------------------------------------------
# 3.8 / 3.9 -- dead-head gradient isolation + excluded output keys
# ---------------------------------------------------------------------------


def test_forward_output_excludes_dead_head_keys() -> None:
    model = _tiny_mil_model(alpha=0.3)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)

    output = model(x, instance_bag, _N_BAGS)
    for forbidden_key in ("fused_prediction", "reliabilities", "modality_predictions"):
        assert forbidden_key not in output


def test_dead_heads_receive_no_gradient() -> None:
    torch.manual_seed(2)
    model = _tiny_mil_model(alpha=0.3)
    model.train()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)
    bag_index = _bag_index_sintetica_de_prueba()
    y_bag = torch.as_tensor(bag_index.y, dtype=torch.float32)

    loss_fn = _tiny_loss(lambda_gate_deviation=0.05)
    output = model(x, instance_bag, _N_BAGS)
    components = loss_fn.compute_components(output, x, y_bag)
    components["total_loss"].backward()

    for regressor in model.base.modality_regressors:
        for parameter in regressor.parameters():
            assert parameter.grad is None

    for reliability_head in model.base.modality_reliability_heads:
        for parameter in reliability_head.parameters():
            assert parameter.grad is None


def test_gradient_liveness_gate_head_attention_and_shared_encoder() -> None:
    torch.manual_seed(2)
    model = _tiny_mil_model(alpha=0.3)
    model.train()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)
    bag_index = _bag_index_sintetica_de_prueba()
    y_bag = torch.as_tensor(bag_index.y, dtype=torch.float32)

    loss_fn = _tiny_loss(lambda_gate_deviation=0.05)
    output = model(x, instance_bag, _N_BAGS)
    components = loss_fn.compute_components(output, x, y_bag)
    components["total_loss"].backward()

    for name, tensor in (
        ("gate_decoder", model.gate_decoder.linear.weight),
        ("attention_pool", model.attention_pool.score_projection.weight),
        ("head", model.head.weight),
        ("shared_encoder", model.base.modality_encoders[0].network[0].weight),
    ):
        assert tensor.grad is not None, f"{name} received no gradient"
        assert float(tensor.grad.abs().sum()) > 0.0, f"{name} received an all-zero gradient"


# ---------------------------------------------------------------------------
# 3.10 / 3.11 -- MILBagLoss composition
# ---------------------------------------------------------------------------


def test_reconstruction_normalization_only_soft_allowed() -> None:
    kwargs = _tiny_loss_kwargs()
    MILBagLoss(**kwargs)  # default "soft" must succeed
    with pytest.raises(ValueError):
        MILBagLoss(reconstruction_normalization="clip", **kwargs)


def test_mil_loss_requires_a_prefitted_kernel_loss() -> None:
    kwargs = _tiny_loss_kwargs()
    kwargs["kernel_loss"] = None
    with pytest.raises(ValueError):
        MILBagLoss(**kwargs)


def test_reconstruction_target_is_original_x_inst_not_propagated() -> None:
    model = _tiny_mil_model(alpha=0.6)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)
    bag_index = _bag_index_sintetica_de_prueba()
    y_bag = torch.as_tensor(bag_index.y, dtype=torch.float32)

    loss_fn = _tiny_loss()
    output = model(x, instance_bag, _N_BAGS)

    against_original = loss_fn.compute_components(output, x, y_bag)
    against_propagated = loss_fn.compute_components(output, output["propagated_inputs"], y_bag)

    assert not torch.allclose(
        against_original["reconstruction_loss_raw"],
        against_propagated["reconstruction_loss_raw"],
    ), (
        "with alpha != 0 the propagated input differs from the original input, so scoring "
        "against each must give different reconstruction losses -- if they matched, the "
        "implementation likely defaulted to propagated_inputs somewhere"
    )


def test_gate_deviation_loss_zero_at_g_equal_one() -> None:
    model = _tiny_mil_model(alpha=0.3)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)
    bag_index = _bag_index_sintetica_de_prueba()
    y_bag = torch.as_tensor(bag_index.y, dtype=torch.float32)

    loss_fn = _tiny_loss(lambda_gate_deviation=0.05)
    output = model(x, instance_bag, _N_BAGS)
    components = loss_fn.compute_components(output, x, y_bag)

    assert components["gate_deviation_loss"].item() == 0.0


def test_no_agreement_or_kl_loss_keys() -> None:
    model = _tiny_mil_model(alpha=0.3)
    model.eval()
    x = _tiny_instance_batch()
    instance_bag = torch.as_tensor(_INSTANCE_BAG, dtype=torch.long)
    bag_index = _bag_index_sintetica_de_prueba()
    y_bag = torch.as_tensor(bag_index.y, dtype=torch.float32)

    loss_fn = _tiny_loss()
    output = model(x, instance_bag, _N_BAGS)
    components = loss_fn.compute_components(output, x, y_bag)

    for forbidden_key in ("agreement_loss", "kl_loss", "kl_loss_raw"):
        assert forbidden_key not in components


# ---------------------------------------------------------------------------
# 3.12 / 3.13 -- entrenar_mil
# ---------------------------------------------------------------------------


def test_entrenar_mil_never_refits_the_kernel_loss_internally() -> None:
    """Fold hygiene (D5): the caller fits `KernelDensityWeightedMSELoss.from_targets`
    on the TRAINING FOLD's log1p(y) only, once, before calling `entrenar_mil` --
    this function must never touch `loss_fn.kernel_loss`'s grid, or it would
    silently leak whatever targets happen to be in `bag_index.y` into the fit."""
    torch.manual_seed(5)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(5).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)

    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()
    grid_before = loss_fn.kernel_loss.grid_values.clone()

    entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=1,
        bag_batch_size=5,
        lr=1e-3,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=5,
        device="cpu",
    )

    assert torch.equal(loss_fn.kernel_loss.grid_values, grid_before)


def test_entrenar_mil_smoke_fit_completes_and_loss_decreases() -> None:
    torch.manual_seed(9)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(9).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)

    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    resultado = entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=2,
        bag_batch_size=5,
        lr=5e-2,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=9,
        device="cpu",
    )

    assert len(resultado["history"]) == 2
    assert np.isfinite(resultado["history"][0]["total_loss"])
    assert np.isfinite(resultado["history"][-1]["total_loss"])
    assert resultado["history"][-1]["total_loss"] < resultado["history"][0]["total_loss"]
    assert not model.training, "entrenar_mil must leave the model in eval mode"


def test_entrenar_mil_rejects_unsupported_optimizer() -> None:
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(1).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)
    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    with pytest.raises(ValueError):
        entrenar_mil(
            model,
            loss_fn,
            X_inst,
            bag_index,
            epochs=1,
            optimizer_name="sgd",
        )


# ---------------------------------------------------------------------------
# Per-epoch monitoring: `historial_epocas`, `verbose`, `progress_callback`
# ---------------------------------------------------------------------------


def test_entrenar_mil_historial_epocas_has_one_record_per_epoch() -> None:
    torch.manual_seed(11)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(11).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)
    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    resultado = entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=3,
        bag_batch_size=5,
        lr=5e-2,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=11,
        device="cpu",
    )

    historial = resultado["historial_epocas"]
    assert len(historial) == 3
    assert [registro["epoca"] for registro in historial] == [1, 2, 3]
    assert {registro["epocas_totales"] for registro in historial} == {3}


def test_entrenar_mil_historial_epocas_records_carry_all_keys_with_right_types() -> None:
    torch.manual_seed(12)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(12).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)
    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    resultado = entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=3,
        bag_batch_size=5,
        lr=5e-2,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=12,
        device="cpu",
    )

    claves_esperadas = {
        "epoca",
        "epocas_totales",
        "perdida_media",
        "segundos_epoca",
        "segundos_acumulados",
        "segundos_restantes_estimados",
    }
    acumulado_previo = -1.0
    for registro in resultado["historial_epocas"]:
        assert set(registro) == claves_esperadas
        assert isinstance(registro["epoca"], int)
        assert isinstance(registro["epocas_totales"], int)
        assert isinstance(registro["perdida_media"], float)
        assert isinstance(registro["segundos_epoca"], float)
        assert isinstance(registro["segundos_acumulados"], float)
        assert isinstance(registro["segundos_restantes_estimados"], float)
        assert registro["segundos_epoca"] >= 0.0
        assert registro["segundos_acumulados"] >= acumulado_previo
        acumulado_previo = registro["segundos_acumulados"]


def test_entrenar_mil_historial_epocas_final_eta_is_zero() -> None:
    torch.manual_seed(14)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(14).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)
    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    resultado = entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=3,
        bag_batch_size=5,
        lr=5e-2,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=14,
        device="cpu",
    )

    assert resultado["historial_epocas"][-1]["segundos_restantes_estimados"] == pytest.approx(
        0.0, abs=1e-9
    )


def test_entrenar_mil_progress_callback_invoked_once_per_epoch_with_same_records() -> None:
    torch.manual_seed(13)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(13).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)
    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    recibidos: list[dict] = []
    resultado = entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=4,
        bag_batch_size=5,
        lr=5e-2,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=13,
        device="cpu",
        progress_callback=recibidos.append,
    )

    assert len(recibidos) == 4
    assert recibidos == resultado["historial_epocas"]


def test_entrenar_mil_verbose_prints_one_line_per_epoch_with_eta(capsys) -> None:
    torch.manual_seed(19)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(19).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)
    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=2,
        bag_batch_size=5,
        lr=5e-2,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=19,
        device="cpu",
        verbose=True,
    )

    salida = capsys.readouterr().out
    lineas = [linea for linea in salida.splitlines() if linea.strip()]
    assert len(lineas) == 2
    for linea in lineas:
        assert re.search(r"\d{2}:\d{2}", linea)


def _entrenar_mil_run(seed: int, *, verbose: bool, con_callback: bool):
    torch.manual_seed(seed)
    bag_index = _bag_index_sintetica_de_prueba()
    X_inst = np.random.default_rng(seed).normal(size=(_N_INST, len(_FEATURES))).astype(np.float32)
    model = _tiny_mil_model(alpha=0.3)
    loss_fn = _tiny_loss()

    callback = (lambda registro: None) if con_callback else None
    resultado = entrenar_mil(
        model,
        loss_fn,
        X_inst,
        bag_index,
        epochs=3,
        bag_batch_size=5,
        lr=5e-2,
        weight_decay=1e-5,
        optimizer_name="adamw",
        seed=seed,
        device="cpu",
        verbose=verbose,
        progress_callback=callback,
    )
    return resultado["model"]


def test_entrenar_mil_monitoring_does_not_perturb_training_determinism() -> None:
    """The whole point of `historial_epocas`/`verbose`/`progress_callback`:
    wall-clock timestamps and printing must never perturb RNG state or
    gradient flow. Two runs with the same seed -- one silent, one fully
    monitored -- must produce bit-identical final parameters."""
    modelo_silencioso = _entrenar_mil_run(17, verbose=False, con_callback=False)
    modelo_monitoreado = _entrenar_mil_run(17, verbose=True, con_callback=True)

    parametros_silencioso = list(modelo_silencioso.parameters())
    parametros_monitoreado = list(modelo_monitoreado.parameters())
    assert len(parametros_silencioso) == len(parametros_monitoreado)
    assert len(parametros_silencioso) > 0
    for parametro_silencioso, parametro_monitoreado in zip(
        parametros_silencioso, parametros_monitoreado
    ):
        assert torch.equal(parametro_silencioso, parametro_monitoreado)
