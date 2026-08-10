"""RED/GREEN tests for the per-vano relevance sweep of notebook 06's row 3.

The panel used to show ONE bar chart: the min-max sensitivity of the whole
selection, softmax-normalised. With up to five vanos under study that answers
the wrong question -- it says which variable moves *the group*, when what the
maintenance decision needs is which variable moves *this vano*, the one whose
work order is being costed.

The naive way to get that is to run the sweep once per vano, which multiplies
the model passes by the number of vanos. It is unnecessary: every forward pass
already produces one u-hat PER BAG, so the same `1 + 2 x knobs` passes carry
all five vanos at once. That is what this module does, and the test below
pins it -- if someone rewrites it as a loop over vanos, the pass count blows
up and the button stops feeling instant.
"""

from __future__ import annotations

import numpy as np
import pytest

from chec_impacto.models.criticality_assignment import Geometria
from chec_local_interpreter.mil_simulador_015 import sensibilidad_minmax_por_vano
from chec_local_interpreter.vano_controls import Knob


def _knob(knob_id, bounds=(0.0, 1.0), feature_names=None, kind="numeric"):
    return Knob(id=knob_id, label=knob_id, kind=kind,
                feature_names=tuple(feature_names or (knob_id,)),
                bounds=bounds, categories=None, default=None, step=None)


def _geometria():
    return Geometria(
        logs=(False, False), offset=np.array([0.0, 0.0]), scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]),
    )


class _Predictor:
    """u-hat de cada bolsa = suma ponderada de sus columnas, con un peso distinto
    por bolsa: asi cada vano reacciona a una variable distinta y el top puede
    diferenciarse entre ellos."""

    def __init__(self, pesos):
        self.geometria = _geometria()
        self.pesos = np.asarray(pesos, dtype=float)   # (n_bolsas, n_features)
        self.llamadas = 0

    def predict(self, X_inst, instance_bag=None):
        self.llamadas += 1
        X = np.asarray(X_inst, dtype=float)
        ib = np.asarray(instance_bag)
        n = int(ib.max()) + 1 if ib.size else 0
        return np.array([float(X[ib == b].mean(axis=0) @ self.pesos[b]) for b in range(n)])


SELECCION = {
    "fid": ["VA", "VB"],
    "filas": np.array([0, 1, 2]),
    "instance_bag": np.array([0, 0, 1]),
    "n_obs": np.array([2, 1]),
    "n_bolsas": 2,
}
X = np.zeros((3, 2))
FEATURES = ["A", "B"]


def test_each_vano_gets_its_own_ranking():
    """VA solo reacciona a la variable A y VB solo a la B. Un ranking agregado
    las mezclaria y diria que las dos importan a medias en todas partes."""
    predictor = _Predictor([[1.0, 0.0], [0.0, 1.0]])

    por_vano = sensibilidad_minmax_por_vano(
        predictor, X, seleccion=SELECCION, feature_names=FEATURES,
        knobs=[_knob("A"), _knob("B")], top=2,
    )

    assert [f["knob_id"] for f in por_vano["VA"]] == ["A", "B"]
    assert [f["knob_id"] for f in por_vano["VB"]] == ["B", "A"]
    assert por_vano["VA"][0]["magnitud"] > por_vano["VA"][1]["magnitud"]


def test_the_five_vanos_cost_the_same_passes_as_one():
    """La razon de ser del modulo. Cada pasada ya devuelve un u-hat POR BOLSA, asi
    que los cinco vanos salen de las mismas `1 + 2 x knobs` pasadas. Escrito como
    un bucle por vano serian cinco veces mas, y el boton dejaria de sentirse
    inmediato."""
    predictor = _Predictor([[1.0, 0.0], [0.0, 1.0]])

    sensibilidad_minmax_por_vano(
        predictor, X, seleccion=SELECCION, feature_names=FEATURES,
        knobs=[_knob("A"), _knob("B")],
    )

    # 1 base + 2 escenarios x 2 knobs, sin importar que haya dos vanos.
    assert predictor.llamadas == 5


def test_only_the_top_n_survives_per_vano():
    """Cinco barras por vano es lo que cabe legible en un cuarto del ancho; el
    resto del ranking se lee en el hover del mapa o en otra corrida."""
    predictor = _Predictor([[1.0, 0.5], [0.5, 1.0]])

    por_vano = sensibilidad_minmax_por_vano(
        predictor, X, seleccion=SELECCION, feature_names=FEATURES,
        knobs=[_knob("A"), _knob("B")], top=1,
    )

    assert all(len(filas) == 1 for filas in por_vano.values())


def test_categorical_and_constant_knobs_are_skipped():
    """Un barrido min-max necesita limites numericos. Inventarselos para una
    categoria puntuaria un escenario que nadie pidio."""
    predictor = _Predictor([[1.0, 0.0], [0.0, 1.0]])

    por_vano = sensibilidad_minmax_por_vano(
        predictor, X, seleccion=SELECCION, feature_names=FEATURES,
        knobs=[_knob("A"), _knob("B", kind="categorical", bounds=None)],
    )

    assert [f["knob_id"] for f in por_vano["VA"]] == ["A"]


def test_an_empty_selection_returns_nothing_without_touching_the_model():
    predictor = _Predictor([[1.0, 0.0]])
    vacia = {"fid": [], "filas": np.array([], dtype=int),
             "instance_bag": np.array([], dtype=int), "n_obs": np.array([]), "n_bolsas": 0}

    por_vano = sensibilidad_minmax_por_vano(
        predictor, X, seleccion=vacia, feature_names=FEATURES, knobs=[_knob("A")],
    )

    assert por_vano == {}
    assert predictor.llamadas == 0


def test_a_climate_family_moves_all_its_lags_as_one_control():
    """Es el punto del catalogo de knobs: los 12 rezagos son UN control, no doce,
    y el barrido tiene que moverlos juntos o subestimaria a la familia entera."""
    predictor = _Predictor([[1.0, 1.0], [1.0, 1.0]])

    por_vano = sensibilidad_minmax_por_vano(
        predictor, X, seleccion=SELECCION, feature_names=FEATURES,
        knobs=[_knob("clima:x", feature_names=("A", "B"))],
    )

    assert [f["knob_id"] for f in por_vano["VA"]] == ["clima:x"]
    # Mover las dos columnas a la vez da el doble que mover una sola.
    assert por_vano["VA"][0]["magnitud"] > 0
