"""RED/GREEN tests for saving/loading a fitted MIL model for the 01.5 simulator.

Notebook 10 trained its final model in memory and discarded it, so the
simulator had nothing to load: `01.5`'s SEAM comment
(`# MODELO = BagPredictor(mil_model, ...)`) named a `mil_model` that no
artifact ever produced.

The feature space is the sharp edge. The MIL model runs on `p` columns built
by `construir_matriz_instancias` (the `procesar_dataset_completo` output plus
COD_CAUSA's frequency and indicator columns), NOT on the raw
`procesar_dataset_completo` output the simulator holds. Handing it the wrong
matrix would not raise -- it would silently score the wrong columns -- so the
artifact carries its feature names and the loader refuses a mismatch.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from chec_impacto.models.criticality_assignment import Geometria
from chec_impacto.models.mgcecdl import MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import construir_edge_index
from chec_impacto.models.mgcecdl_mil import MILBagRegressor
from chec_impacto.models.mil_persistencia import (
    cargar_modelo_mil,
    guardar_modelo_mil,
)

_FEATURES = ["a", "b", "c", "d", "e", "ind"]
_EDGES = [
    {"source": "a", "target": "b", "weight": 0.5},
    {"source": "b", "target": "c", "weight": 0.8},
    {"source": "c", "target": "d", "weight": 0.3},
    {"source": "d", "target": "e", "weight": 0.6},
]
_MODALIDADES = {"climaticos": [0, 1, 2], "estructurales": [3, 4, 5]}


def _geometria() -> Geometria:
    return Geometria(
        logs=(False, True),
        offset=np.array([1.0, -3.0]),
        scale=np.array([45.0, 7.424386]),
        centroides=np.array([[0.0, 0.55], [0.02, 0.65], [0.04, 0.75], [0.06, 0.88]]),
    )


def _adjacency() -> np.ndarray:
    pos = {n: i for i, n in enumerate(_FEATURES)}
    m = np.zeros((len(_FEATURES), len(_FEATURES)), dtype=np.float32)
    for e in _EDGES:
        m[pos[e["source"]], pos[e["target"]]] = e["weight"]
    return m


def _modelo(fusion: str = "film") -> MILBagRegressor:
    torch.manual_seed(0)
    base = MGCECDLRegressor(
        modality_feature_indices=_MODALIDADES, hidden_dim=16, embed_dim=4, dropout=0.0
    )
    kw = {"film_modulated_modality": "estructurales"} if fusion == "film" else {}
    return MILBagRegressor(
        base=base,
        adjacency=_adjacency(),
        edge_index=construir_edge_index(_adjacency(), _FEATURES, _EDGES),
        alpha=0.2,
        attn_dim=8,
        fusion=fusion,
        **kw,
    )


def _guardar(tmp_path, fusion="film"):
    ruta = tmp_path / "mil.pt"
    guardar_modelo_mil(
        ruta,
        modelo=_modelo(fusion),
        features=_FEATURES,
        modalidades=_MODALIDADES,
        adjacency=_adjacency(),
        edges=_EDGES,
        geometria=_geometria(),
        hiperparametros={"hidden_dim": 16, "embed_dim": 4, "dropout": 0.0,
                         "alpha": 0.2, "attn_dim": 8},
        metadatos={"macro_f1": 0.870982, "fusion": fusion},
    )
    return ruta


def _X(n: int = 7) -> np.ndarray:
    return np.random.default_rng(0).normal(size=(n, len(_FEATURES))).astype(np.float32)


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------


def test_saved_model_reloads_with_identical_predictions(tmp_path):
    """Compared through the same API the simulator uses, not through p_bag.

    `BagPredictor.predict` returns `expm1(p_bag)` unclamped, so reconstructing
    `p_bag` from it needs `log1p` of a possibly negative number -- comparing
    predictor to predictor tests the thing that actually ships.
    """
    from chec_impacto.interpretability.mil_vano_ventana import BagPredictor

    ruta = _guardar(tmp_path)
    original = BagPredictor(_modelo("film"), _FEATURES, _geometria(), device="cpu")
    recargado = cargar_modelo_mil(ruta, device="cpu")

    X = _X()
    assert np.allclose(
        recargado.predict(X, instance_bag=None),
        original.predict(X, instance_bag=None),
        rtol=1e-6,
        atol=1e-6,
    )


def test_loaded_object_is_ready_for_the_simulator_contract(tmp_path):
    from chec_impacto.interpretability.mil_vano_ventana import predict_fn

    predictor = cargar_modelo_mil(_guardar(tmp_path), device="cpu")
    salida = predict_fn(predictor, _X(5), device="cpu", batch_size=8)

    assert salida["fused_probs"].shape == (5, 4)
    assert salida["predicted_classes"].shape == (5,)
    assert np.allclose(salida["fused_probs"].sum(axis=1), 1.0, atol=1e-6)
    assert set(np.unique(salida["predicted_classes"])) <= {0, 1, 2, 3}


def test_artifact_carries_its_feature_names_and_metadata(tmp_path):
    predictor = cargar_modelo_mil(_guardar(tmp_path), device="cpu")
    assert list(predictor.feature_names) == _FEATURES
    assert predictor.metadatos["macro_f1"] == pytest.approx(0.870982)
    assert predictor.metadatos["fusion"] == "film"


# ---------------------------------------------------------------------------
# The failure that would be silent
# ---------------------------------------------------------------------------


def test_loader_refuses_a_feature_name_mismatch(tmp_path):
    """Scoring the wrong columns does not raise on its own -- it just lies."""
    ruta = _guardar(tmp_path)
    with pytest.raises(ValueError, match="features"):
        cargar_modelo_mil(ruta, device="cpu", features_esperadas=["otra", "cosa"])


def test_loader_accepts_the_matching_feature_names(tmp_path):
    predictor = cargar_modelo_mil(
        _guardar(tmp_path), device="cpu", features_esperadas=_FEATURES
    )
    assert list(predictor.feature_names) == _FEATURES


def test_concat_fusion_round_trips_too(tmp_path):
    """The artifact must not hardcode the arm it happened to be trained with."""
    predictor = cargar_modelo_mil(_guardar(tmp_path, fusion="concat"), device="cpu")
    assert predictor.metadatos["fusion"] == "concat"
    assert predictor.predict(_X(4), instance_bag=None).shape == (4,)


def test_missing_artifact_names_the_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="mil"):
        cargar_modelo_mil(tmp_path / "no_existe_mil.pt", device="cpu")
