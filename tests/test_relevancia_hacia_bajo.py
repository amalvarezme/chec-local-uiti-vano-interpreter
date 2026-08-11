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
    plan_hacia_clase_minima,
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
        # `% len(self.funciones)`: el plan puntua todos los ensayos de una ronda en UNA
        # pasada, apilandolos con las bolsas desplazadas -- el ensayo `t` usa las bolsas
        # `t * n_bolsas + b` --, asi que el mismo vano aparece varias veces con indices
        # distintos. El modulo lo devuelve a su propia funcion de respuesta, que es lo
        # que este doble modela: una `f` por VANO, no por posicion en la matriz.
        return np.array([self.funciones[b % len(self.funciones)](X[ib == b].mean(axis=0))
                         for b in range(n)])


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


def test_categorical_knobs_are_ranked_too_and_only_constants_are_skipped():
    """El barrido anterior saltaba los categoricos, y con ellos se caian del ranking
    el conductor, el calibre del neutro y el tipo de proteccion: tres de las obras
    que CHEC efectivamente ejecuta. El usuario perdia libertad justo sobre la mitad
    de intervencion. Su "rejilla" son sus categorias. El constante si queda fuera:
    un unico valor observado no mueve nada y probarlo solo gasta una pasada."""
    predictor = _Predictor([lambda v: float(v[0] + v[1]), lambda v: 1.0])
    knobs = [_knob("NUM", feature_names=("x",)),
             Knob(id="CAT", label="CAT", kind="categorical", feature_names=("y",),
                  bounds=None, categories=("a", "b"), default=None, step=None),
             _knob("CONST", kind="constant", bounds=None, feature_names=("y",))]

    etiquetas = [f["label"] for f in relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES,
        knobs=knobs)["VA"]["filas"]]

    assert "CAT" in etiquetas
    assert "CONST" not in etiquetas


def test_the_top_reserves_room_for_both_groups_of_variables():
    """Un ranking copado por las familias climaticas no deja ni una palanca que una
    cuadrilla pueda ejecutar, y el panel existe para sostener una orden de trabajo.
    Aqui las tres de escenario bajan mas que las dos de intervencion, y aun asi el
    top de cuatro reserva sitio para las dos."""
    predictor = _Predictor([lambda v: float(v[0]), lambda v: 1.0])
    knobs = [_knob(f"E{i}", feature_names=("x",)) for i in range(3)]
    knobs += [_knob(f"I{i}", feature_names=("y",)) for i in range(2)]
    grupos = {f"E{i}": "Escenario" for i in range(3)}
    grupos.update({f"I{i}": "Intervencion" for i in range(2)})

    filas = relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs,
        top=4, grupos=grupos)["VA"]["filas"]

    presentes = {f["grupo"] for f in filas}
    assert presentes == {"Escenario", "Intervencion"}
    assert len(filas) == 4


def test_without_groups_the_top_is_a_plain_top():
    """La reserva es una decision del llamador y no algo que el modulo imponga."""
    predictor = _Predictor([lambda v: float(v[0]), lambda v: 1.0])
    knobs = [_knob(f"K{i}", feature_names=("x",)) for i in range(4)]

    filas = relevancia_hacia_uiti_minimo(
        predictor, _X(), seleccion=SELECCION, feature_names=FEATURES, knobs=knobs,
        top=2)["VA"]["filas"]

    assert len(filas) == 2


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


# --- el plan combinado ------------------------------------------------------------------
#
# Medido sobre 59 bolsas de 40 circuitos: en Medio, 20 de 33 alcanzan el grupo Bajo con
# UNA sola variable; en Medio-Alto, 0 de 18; en Alto, 0 de 8. No es una rareza de un vano,
# es el caso normal justo en los grupos donde la pregunta importa, y por eso el plan
# combinado no es un extra sino la respuesta.


def test_the_plan_chains_variables_until_the_vano_reaches_the_low_group():
    """Ninguna de las dos sola alcanza; juntas si. Es exactamente la situacion de un
    vano en Medio-Alto, donde la mejor variable cubre el 60% del camino."""
    # Los centroides estan en log10(u) = -1, 0, 1 y 2, asi que el grupo mas bajo
    # empieza por debajo de 10^-0,5 = 0,316. Cada variable divide u por 20 al llevarla
    # a su maximo: una sola lo deja en 5 -- fuera --, las dos juntas en 0,25 -- dentro.
    predictor = _Predictor([lambda v: 100.0 * 0.05 ** (v[0] / 10.0) * 0.05 ** (v[1] / 10.0),
                            lambda v: 0.01])
    knobs = [_knob("A", feature_names=("x",)), _knob("B", feature_names=("y",))]

    plan = plan_hacia_clase_minima(
        predictor, np.zeros((3, 2)), seleccion=SELECCION, feature_names=FEATURES,
        knobs=knobs, puntos=3, max_pasos=3)

    va = plan["VA"]
    assert [p["label"] for p in va["pasos"]] == ["A", "B"]
    assert va["u_final"] < va["u_base"]
    assert va["alcanza"] is True


def test_the_plan_stops_as_soon_as_the_low_group_is_reached():
    """Un plan de mantenimiento no agrega obra despues de haber conseguido el
    objetivo: cada paso de mas es dinero que no compra nada."""
    predictor = _Predictor([lambda v: 100.0 - 10.0 * v[0], lambda v: 0.01])
    knobs = [_knob("BASTA", feature_names=("x",)), _knob("SOBRA", feature_names=("y",))]

    plan = plan_hacia_clase_minima(
        predictor, np.zeros((3, 2)), seleccion=SELECCION, feature_names=FEATURES,
        knobs=knobs, puntos=3, max_pasos=4)

    assert [p["label"] for p in plan["VA"]["pasos"]] == ["BASTA"]


def test_the_plan_reports_the_shortfall_when_the_group_is_out_of_reach():
    """Cuando ni moviendolo todo se llega, decirlo vale mas que un plan que
    insinua lo contrario: se devuelve lo mejor alcanzado y `alcanza=False`."""
    predictor = _Predictor([lambda v: 1000.0 - v[0], lambda v: 0.01])
    knobs = [_knob("POCO", feature_names=("x",))]

    plan = plan_hacia_clase_minima(
        predictor, np.zeros((3, 2)), seleccion=SELECCION, feature_names=FEATURES,
        knobs=knobs, puntos=3, max_pasos=3)

    va = plan["VA"]
    assert va["alcanza"] is False
    assert va["u_final"] < va["u_base"]
    assert va["pasos"], "aun sin alcanzar, lo conseguido se reporta"


def test_a_vano_already_in_the_low_group_gets_an_empty_plan():
    """No hay obra que proponerle: ya esta donde se queria llegar."""
    predictor = _Predictor([lambda v: 0.01, lambda v: 0.01])
    knobs = [_knob("A", feature_names=("x",))]

    plan = plan_hacia_clase_minima(
        predictor, np.zeros((3, 2)), seleccion=SELECCION, feature_names=FEATURES,
        knobs=knobs, puntos=3)

    assert plan["VA"]["pasos"] == []
    assert plan["VA"]["alcanza"] is True


def test_a_knob_is_used_at_most_once_per_vano():
    """Un plan que reajusta dos veces la misma variable no es una orden de trabajo
    mas barata, es la misma obra contada dos veces."""
    predictor = _Predictor([
        lambda v: 100.0 * 0.05 ** (v[0] / 10.0) * 0.05 ** (v[1] / 10.0), lambda v: 0.01])
    knobs = [_knob("A", feature_names=("x",)), _knob("B", feature_names=("y",))]

    pasos = plan_hacia_clase_minima(
        predictor, np.zeros((3, 2)), seleccion=SELECCION, feature_names=FEATURES,
        knobs=knobs, puntos=3, max_pasos=4)["VA"]["pasos"]

    assert len({p["knob_id"] for p in pasos}) == len(pasos)
