"""Persist and reload a fitted `MILBagRegressor` for the 01.5 simulator.

Notebook 10 trained its final model inside a cell and discarded it, so the
simulator's SEAM comment (`# MODELO = BagPredictor(mil_model, ...)`) named a
`mil_model` no artifact ever produced. This module is that artifact.

The feature space is the sharp edge. `MILBagRegressor` runs on the `p`
columns `construir_matriz_instancias` builds -- the `procesar_dataset_completo`
output PLUS COD_CAUSA's frequency and indicator columns -- not on the raw
matrix the simulator already holds. Handing it the wrong matrix does not
raise: shapes can even match by accident, and the model simply scores the
wrong columns. So the artifact carries `features` and `cargar_modelo_mil`
refuses a mismatch instead of trusting the caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from chec_impacto.interpretability.mil_vano_ventana import BagPredictor
from chec_impacto.models.criticality_assignment import Geometria
from chec_impacto.models.mgcecdl import MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import construir_edge_index
from chec_impacto.models.mgcecdl_mil import MILBagRegressor

FORMATO_ARTEFACTO = 1


def guardar_modelo_mil(
    ruta: str | Path,
    *,
    modelo: MILBagRegressor,
    features: Sequence[str],
    modalidades: Mapping[str, Sequence[int]],
    adjacency: np.ndarray,
    edges: Sequence[Mapping[str, Any]],
    geometria: Geometria,
    hiperparametros: Mapping[str, Any],
    metadatos: Mapping[str, Any] | None = None,
) -> Path:
    """Write everything needed to rebuild `modelo` byte-for-byte.

    The graph is stored as `adjacency` + `edges` rather than as a built
    `GraphEdgeIndex`: `MILBagRegressor` rejects an edge index that disagrees
    with its adjacency, and rebuilding both from the same stored pair keeps
    that guard meaningful after a round trip.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "formato": FORMATO_ARTEFACTO,
        "state_dict": {k: v.cpu() for k, v in modelo.state_dict().items()},
        "features": list(features),
        "modalidades": {k: list(v) for k, v in modalidades.items()},
        "adjacency": np.asarray(adjacency, dtype=np.float32),
        "edges": [dict(e) for e in edges],
        "geometria": {
            "logs": list(geometria.logs),
            "offset": np.asarray(geometria.offset),
            "scale": np.asarray(geometria.scale),
            "centroides": np.asarray(geometria.centroides),
        },
        "hiperparametros": dict(hiperparametros),
        "fusion": modelo.fusion,
        "film_modulated_modality": getattr(modelo, "film_modulated_modality", None),
        "metadatos": dict(metadatos or {}),
    }
    torch.save(payload, ruta)
    return ruta


def cargar_modelo_mil(
    ruta: str | Path,
    *,
    device: str = "cpu",
    features_esperadas: Sequence[str] | None = None,
) -> BagPredictor:
    """Rebuild the fitted model and wrap it in a `BagPredictor`.

    `features_esperadas` is the guard the simulator should always pass: the
    column order the caller actually built. A mismatch here is the one error
    that would otherwise stay silent all the way to a published map.
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el artefacto del modelo MIL: {ruta}")

    payload = torch.load(ruta, map_location="cpu", weights_only=False)
    if payload.get("formato") != FORMATO_ARTEFACTO:
        raise ValueError(
            f"Formato de artefacto {payload.get('formato')!r} desconocido "
            f"(esperado {FORMATO_ARTEFACTO})."
        )

    features = list(payload["features"])
    if features_esperadas is not None and list(features_esperadas) != features:
        faltan = [f for f in features if f not in set(features_esperadas)]
        sobran = [f for f in features_esperadas if f not in set(features)]
        raise ValueError(
            "Las features del artefacto no coinciden con las que construyo quien llama: "
            f"{len(features)} guardadas vs {len(list(features_esperadas))} recibidas. "
            f"Faltan en la entrada: {faltan[:5]}. Sobran: {sobran[:5]}. "
            "El modelo puntuaria columnas equivocadas sin fallar."
        )

    hp = dict(payload["hiperparametros"])
    adjacency = np.asarray(payload["adjacency"], dtype=np.float32)
    base = MGCECDLRegressor(
        modality_feature_indices=payload["modalidades"],
        hidden_dim=int(hp["hidden_dim"]),
        embed_dim=int(hp["embed_dim"]),
        dropout=float(hp.get("dropout", 0.1)),
    )
    modelo = MILBagRegressor(
        base=base,
        adjacency=adjacency,
        edge_index=construir_edge_index(adjacency, features, payload["edges"]),
        alpha=float(hp["alpha"]),
        attn_dim=int(hp.get("attn_dim", 64)),
        fusion=payload["fusion"],
        film_modulated_modality=payload.get("film_modulated_modality"),
    )
    modelo.load_state_dict(payload["state_dict"])
    modelo.eval()

    g = payload["geometria"]
    geometria = Geometria(
        logs=(bool(g["logs"][0]), bool(g["logs"][1])),
        offset=np.asarray(g["offset"], dtype=np.float64),
        scale=np.asarray(g["scale"], dtype=np.float64),
        centroides=np.asarray(g["centroides"], dtype=np.float64),
    )

    predictor = BagPredictor(modelo, features, geometria, device=device)
    predictor.metadatos = dict(payload.get("metadatos", {}))
    return predictor
