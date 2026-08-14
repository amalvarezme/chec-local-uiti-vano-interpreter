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

import json
import re
from pathlib import Path

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


# --- El cableado del cuaderno: que variables entran al ranking -------------------------
#
# El barrido puntua lo que se le pase. Que el ranking se quede en los dos conjuntos
# OFRECIDOS -- intervencion y escenario -- no es una propiedad de `sensibilidad_minmax_por_vano`
# sino del argumento que el cuaderno le manda, y por eso se fija aqui contra la fuente.

NOTEBOOK = (
    Path(__file__).resolve().parents[1]
    / "notebooks"
    / "base_apps"
    / "06_uiti_vano_explicabilidad_simulador.ipynb"
)


@pytest.fixture(scope="module")
def fuente() -> str:
    celdas = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    return "\n".join("".join(celda["source"]) for celda in celdas)


def test_the_ranking_only_sweeps_the_variables_the_panel_offers(fuente):
    """El ranking recorre `KNOBS_PANEL` -- el mismo filtro que arma las cuatro
    columnas del panel -- y nunca `KNOBS` entero.

    Con `KNOBS` entrarian al top las tres refutadas y las cinco de lectura unica,
    y el panel terminaria diciendo que la variable mas relevante de un vano es
    `CNT_TRF`: los trafos afectados EN LA FALLA, que se miden DESPUES del evento
    que el modelo intenta anticipar. Eso no es un ranking flojo, es la flecha del
    analisis al reves, y sostiene ordenes de trabajo que no arreglan nada.

    Se fija contra la fuente porque el filtro no vive dentro del barrido: es el
    argumento que el cuaderno le pasa, y cambiarlo por `KNOBS` no rompe nada
    visible -- solo agrega ocho variables al ranking en silencio.
    """
    assert "KNOBS_PANEL = knobs_simulables(KNOBS)" in fuente
    llamada = re.search(
        r"return relevancia_hacia_uiti_minimo\((.*?)\n    \)", fuente, re.S
    )
    assert llamada is not None
    argumentos = llamada.group(1)
    assert "knobs=KNOBS_PANEL" in argumentos
    assert "knobs=KNOBS," not in argumentos


def test_the_blocked_variables_reach_the_simulation_but_never_the_ranking(fuente):
    """Quitarlas del ranking no las saca de la SIMULACION: un override solo se
    escribe si se fija, asi que entran al modelo con el valor OBSERVADO de cada
    vano. Por eso `simular_bolsas` sigue resolviendo contra `KNOBS` completo
    mientras el barrido se queda con los ofrecidos -- son dos preguntas
    distintas, y confundirlas es lo que este par de pruebas separa."""
    assert "KNOBS_BLOQUEADOS = knobs_bloqueados(KNOBS)" in fuente
    # `expand_knob_overrides` resuelve que features toca cada control fijado, y
    # solo llegan ahi los que el panel ofrecio.
    assert "expand_knob_overrides(\n" in fuente
    assert "{knob_id: control.value for knob_id, control in controles.items()}, KNOBS)" in fuente


def test_the_panel_ranks_by_achievable_drop_and_not_by_unsigned_sensitivity(fuente):
    """El cambio de pregunta. La barra ya no mide cuanto MUEVE una variable sino
    cuanto BAJA el UITI del vano, en ordenes de magnitud, y el hover trae el valor
    que lo consigue -- asi la lista se lee como una instruccion y no como un
    puntaje. Medido sobre un vano real, los dos rankings no comparten ni una de sus
    cinco primeras variables."""
    assert "_y.append(_fila['caida_log'])" in fuente
    assert "Llevarla a <b>{_valor}</b>" in fuente
    # El valor de un control CATEGORICO es texto -- su categoria --, y desde que el
    # ranking los incluye, formatearlo con `:,.4g` revienta el repintado entero. Se
    # detecto simulando sobre vanos reales: `CONDUCTOR` entro al top y tumbo el panel.
    assert "isinstance(_fila['valor'], (int, float))" in fuente
    assert "'magnitud'" not in fuente, "queda una lectura del barrido min-max viejo"


def test_the_green_bar_means_that_variable_alone_changes_the_group(fuente):
    """Verde es el mismo verde del recuadro del mapa simulado y significa lo mismo:
    baja de grupo de criticidad. Un vano que YA esta en el mas bajo no puede pintar
    nada de verde -- lo cumpliria con todo -- y eso lo decide el modulo, no el
    cuaderno."""
    assert "COLOR_CAJA_MEJORA if _fila['alcanza']" in fuente
    assert "_datos['ya_en_clase_minima']" in fuente


def test_the_grid_has_more_than_the_two_ends(fuente):
    """Medido sobre este modelo, 10 de los 15 controles numericos tienen su mejor
    valor en el INTERIOR del rango para alguna bolsa. Con dos puntos se muestrea
    justo donde el optimo no esta."""
    m = re.search(r"^PUNTOS_REJILLA_RELEVANCIA = (\d+)$", fuente, re.M)
    assert m and int(m.group(1)) >= 3
    assert "puntos=PUNTOS_REJILLA_RELEVANCIA" in fuente
