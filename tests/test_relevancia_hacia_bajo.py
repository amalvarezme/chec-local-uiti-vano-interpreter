"""RED/GREEN tests for the relevance ranking that aims AT the low criticality group.

The panel used to rank variables by min-max sensitivity: for each control, push it
to both ends of its range and keep `max(|delta-|, |delta+|)`. That answers "which
variable moves this vano the most", which is not the question a work order asks.
It has two defects for the question that IS asked -- *which variable can take this
vano down to the low group?*:

  1. The magnitude is DIRECTIONLESS. A variable that raises the risk hard at both
     extremes outranks one that lowers it a little, and the top of the list fills
     with levers you must not pull.
  2. It only looks at the two ENDS. Measured on the real model over one circuit's
     bags, 10 of the 15 numeric controls have their best value in the INTERIOR of
     their range for at least one bag -- `DDT` for every single one. The model is
     strongly non-monotone, so the ends are simply the wrong two points to sample.

What replaces it scans a grid across each control's range, keeps the value that
MINIMISES the predicted UITI of each bag, and ranks by how far down it gets --
measured in orders of magnitude of `u`, which is the axis the KMeans geometry
itself uses. Each row therefore carries the value that achieves it, so the ranking
reads as an instruction and not as a score.

It also states the target. With `n_obs` fixed -- it is never simulated, it is the
other axis of the class space -- there is a `u` below which the bag lands in the
lowest group, and that threshold shrinks fast as events pile up (measured: 4,41 at
one event, 0,0029 at forty-six). Saying "this variable covers 60% of the way" needs
that number, and saying "no single variable gets there" is worth more than a
ranking that pretends otherwise.
"""

from __future__ import annotations

import numpy as np
import pytest

from chec_impacto.models.criticality_assignment import Geometria
from chec_local_interpreter.mil_simulador_015 import (
    relevancia_hacia_uiti_minimo,
    umbral_u_para_clase_minima,
)
from chec_local_interpreter.vano_controls import Knob


def _knob(knob_id, bounds=(0.0, 10.0), feature_names=None, kind="numeric"):
    return Knob(id=knob_id, label=knob_id, kind=kind,
                feature_names=tuple(feature_names or (knob_id,)),
                bounds=bounds, categories=None, default=None, step=None)


def _geometria():
    """Cuatro centroides ordenados por el eje de u, que es lo que hace que "el
    grupo mas bajo" signifique "el de menor UITI"."""
    return Geometria(
        logs=(False, True), offset=np.array([0.0, 0.0]), scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, -1.0], [0.0, 0.0], [0.0, 1.0], [0.0, 2.0]]),
    )


class _Predictor:
    """u-hat de la bolsa = `f(valor de la columna 0)`, con una `f` por bolsa.

    Deja escribir modelos NO monotonos, que es la propiedad que separa a este
    barrido del anterior.
    """

    def __init__(self, funciones):
        self.geometria = _geometria()
        self.funciones = funciones
        self.llamadas = 0

    def predict(self, X_inst, instance_bag=None):
        self.llamadas += 1
        X = np.asarray(X_inst, dtype=float)
        ib = np.asarray(instance_bag)
        n = int(ib.max()) + 1 if ib.size else 0
        return np.array([self.funciones[b](X[ib == b].mean(axis=0)) for b in range(n)])


SELECCION = {
    "fid": ["VA", "VB"],
    "filas": np.array([0, 1, 2]),
    "instance_bag": np.array([0, 0, 1]),
    "n_obs": np.array([2, 1]),
    "n_bolsas": 2,
}
FEATURES = ["x", "y"]


def _X():
    return np.array([[5.0, 1.0], [5.0, 1.0], [5.0, 1.0]])


# --- el objetivo: que u hace falta para caer en el grupo mas bajo ----------------------


def test_the_threshold_is_the_largest_u_that_still_lands_in_the_lowest_group():
    """Es el numero que convierte el ranking en una instruccion: sin el, "baja el
    UITI un 70%" no dice si eso alcanza para cambiar de grupo o se queda a
    mitad de camino."""
    umbral = umbral_u_para_clase_minima(n_obs=1.0, geometria=_geometria())

    assert umbral is not None
    clase_justo_debajo, _ = _clase(umbral * 0.99, 1.0)
    clase_encima, _ = _clase(umbral * 1.2, 1.0)
    assert clase_justo_debajo == 0
    assert clase_encima != 0


def _clase(u, n_obs):
    from chec_impacto.models.criticality_assignment import asignar_clase
    clases, _ = asignar_clase(np.array([float(n_obs)]), np.array([float(u)]), _geometria())
    return int(clases[0]), None


def test_an_unreachable_low_group_returns_none_instead_of_a_made_up_number():
    """Si el eje de eventos por si solo saca a la bolsa del grupo mas bajo, ningun
    UITI la devuelve alli. Devolver un umbral igual daria una meta que el
    simulador no puede cumplir, y el panel la presentaria como alcanzable."""
    lejos = Geometria(
        logs=(False, True), offset=np.array([0.0, 0.0]), scale=np.array([1.0, 1.0]),
        # El centroide del grupo bajo vive en n_obs=0; con n_obs=50 la bolsa cae
        # siempre mas cerca de otro, por bajo que sea su u.
        centroides=np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 1.0], [50.0, 2.0]]),
    )
    assert umbral_u_para_clase_minima(n_obs=50.0, geometria=lejos) is None


# --- el ranking ------------------------------------------------------------------------


def test_a_variable_that_only_raises_the_risk_ranks_below_one_that_lowers_it():
    """El defecto que este barrido corrige. Con la magnitud sin signo, `SUBE`
    encabezaba el ranking por mover mucho -- hacia arriba -- y el panel ofrecia
    como primera palanca justo la que no hay que tocar."""
    # SUBE mueve u de 1 a 100; BAJA lo mueve de 1 a 0,5. En magnitud gana SUBE.
    predictor = _Predictor([lambda v: 1.0 + 99.0 * (v[0] / 10.0), lambda v: 1.0])
    knobs = [_knob("SUBE", feature_names=("x",)), _knob("BAJA", feature_names=("y",))]
    X = np.array([[0.0, 10.0], [0.0, 10.0], [0.0, 10.0]])
    predictor.funciones = [lambda v: 1.0 + 99.0 * (v[0] / 10.0) - 0.5 * (1 - v[1] / 10.0),
                           lambda v: 1.0]

    resultado = relevancia_hacia_uiti_minimo(
        predictor, X, seleccion=SELECCION, feature_names=FEATURES, knobs=knobs, top=2)

    orden = [f["label"] for f in resultado["VA"]["filas"]]
    assert orden[0] == "SUBE" or orden[0] == "BAJA"
    # Lo que se exige: la fila de SUBE no puede reportar una caida positiva, porque
    # llevada a su mejor valor no baja nada.
    fila_sube = next(f for f in resultado["VA"]["filas"] if f["label"] == "SUBE")
    assert fila_sube["caida_log"] >= 0.0
    assert fila_sube["u_optimo"] <= resultado["VA"]["u_base"] + 1e-9


def test_the_best_value_can_be_inside_the_range_and_is_reported():
    """La otra correccion. Medido sobre el modelo real, 10 de 15 controles tienen
    su mejor valor en el INTERIOR del rango para alguna bolsa -- `DDT` para
    todas --, asi que mirar solo los dos extremos muestrea los puntos
    equivocados. Aqui `u` es minimo en x=5, ni en 0 ni en 10."""
    predictor = _Predictor([lambda v: 1.0 + (v[0] - 5.0) ** 2, lambda v: 1.0])
    knobs = [_knob("PARABOLA", feature_names=("x",))]

    resultado = relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs,
        puntos=11)

    fila = resultado["VA"]["filas"][0]
    assert fila["valor"] == pytest.approx(5.0)
    assert fila["u_optimo"] == pytest.approx(1.0)


def test_the_ranking_says_whether_the_vano_reaches_the_low_group():
    """"Baja el UITI un 70%" no es una respuesta: la pregunta es si cambia de
    grupo. Y cuando NINGUNA variable sola llega -- medido, le pasa a un vano de
    Medio-Alto con u=271 --, decirlo vale mas que un ranking que lo insinua."""
    predictor = _Predictor([lambda v: 100.0 - 9.0 * v[0], lambda v: 1.0])
    knobs = [_knob("INSUFICIENTE", feature_names=("x",))]

    resultado = relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs)

    va = resultado["VA"]
    assert va["objetivo_u"] is not None
    assert va["filas"][0]["alcanza"] is False
    assert not va["alcanza_alguna"]


def test_the_whole_selection_costs_one_sweep_and_not_one_per_vano():
    """La propiedad que mantiene inmediato el boton: cada pasada ya devuelve un
    u-hat POR BOLSA, asi que los cinco vanos salen del mismo barrido. Escrito
    como un bucle sobre vanos serian cinco veces mas pasadas."""
    predictor = _Predictor([lambda v: float(v[0]), lambda v: float(v[0])])
    knobs = [_knob("A", feature_names=("x",)), _knob("B", feature_names=("y",))]

    relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs,
        puntos=7)

    assert predictor.llamadas == 1 + 2 * 7


def test_categorical_and_constant_knobs_are_skipped():
    """Sin limites numericos no hay rejilla que recorrer, e inventarles un rango
    puntuaria un escenario que nadie pidio. Mismo criterio que el barrido anterior."""
    predictor = _Predictor([lambda v: float(v[0]), lambda v: float(v[0])])
    knobs = [_knob("NUM", feature_names=("x",)),
             _knob("CAT", kind="categorical", bounds=None, feature_names=("y",)),
             _knob("CONST", kind="constant", bounds=None, feature_names=("y",))]

    resultado = relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs)

    assert [f["label"] for f in resultado["VA"]["filas"]] == ["NUM"]


def test_only_the_top_n_survives_per_vano():
    predictor = _Predictor([lambda v: float(v[0] + v[1]), lambda v: 1.0])
    knobs = [_knob("A", feature_names=("x",)), _knob("B", feature_names=("y",))]

    resultado = relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs, top=1)

    assert len(resultado["VA"]["filas"]) == 1


def test_an_empty_selection_returns_nothing_without_touching_the_model():
    predictor = _Predictor([])
    vacia = {"fid": [], "filas": np.array([], dtype=int),
             "instance_bag": np.array([], dtype=int), "n_obs": np.array([]), "n_bolsas": 0}

    assert relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=vacia, feature_names=FEATURES,
        knobs=[_knob("A", feature_names=("x",))]) == {}
    assert predictor.llamadas == 0


def test_a_vano_already_in_the_low_group_is_not_reported_as_reaching_it():
    """`alcanza` promete un CAMBIO de grupo. Un vano que ya esta en el mas bajo lo
    cumple trivialmente con cualquier variable -- medido, uno con u=0,415 y meta
    4,24 daba las diez en verde --, y el panel terminaba senialando como palancas
    decisivas a diez variables que no mueven nada. Cuando no hay adonde bajar, la
    respuesta correcta es decirlo, no pintar el panel de verde."""
    # u=1 con n_obs=1 cae en el grupo mas bajo de la geometria de prueba.
    predictor = _Predictor([lambda v: 0.01, lambda v: 0.01])
    knobs = [_knob("A", feature_names=("x",))]

    resultado = relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs)

    va = resultado["VA"]
    assert va["ya_en_clase_minima"] is True
    assert va["filas"][0]["alcanza"] is False
    assert va["alcanza_alguna"] is False
