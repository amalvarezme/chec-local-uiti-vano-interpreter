"""RED/GREEN tests for notebook 06's PER-VANO simulation.

Until now the simulator applied one value per variable across the whole
selection: `aplicar_overrides_instancias` writes `X_sim[:, col] = valor` over
every instance at once. That answers "what if it rained 40 mm on all of
them", which is the right question for a weather scenario and the wrong one
for maintenance -- pruning is scheduled vano by vano, and the panel could not
express "raise the grounding of this one and leave the other four alone".

This module adds the two pieces that make per-vano scenarios possible:

  `valores_actuales_por_vano`
      What each control should START at: the vano's OWN current value in the
      active window. A control that starts at a global default silently asks
      the user to re-enter data the model already has, and any variable left
      untouched would then be simulated at the wrong value. When a vano has
      several instances inside the window the numeric summary is the MEDIAN
      -- the mean is dragged by the storm hour that motivated the row -- and
      the categorical summary is the MODE, because a median over label codes
      is a code that may not even exist.

  `aplicar_overrides_por_vano`
      Writes each vano's values into ONLY that vano's instance rows, found
      through `instance_bag`. Writing them broadcast, as before, would let
      the last vano's value overwrite everyone else's.

Both keep `aplicar_overrides_instancias`'s policy on failure: one bad control
is reported and every other one still applies, because throwing away a
simulation the user is waiting on is worse than a partial answer that says
what it skipped.
"""

from __future__ import annotations

import numpy as np
import pytest

from chec_local_interpreter.mil_simulador_015 import (
    aplicar_overrides_por_vano,
    valores_actuales_por_vano,
)
from chec_local_interpreter.vano_controls import Knob


class _Encoder:
    """El `LabelEncoder` visto por el modulo: `classes_` y nada mas."""

    classes_ = np.array(["A", "B", "C"])

    def transform(self, valores):
        return np.array([list(self.classes_).index(v) for v in valores])


def _knob(knob_id, kind="numeric", feature_names=None, categories=None):
    return Knob(
        id=knob_id, label=knob_id, kind=kind,
        feature_names=tuple(feature_names or (knob_id,)),
        bounds=(0.0, 100.0) if kind == "numeric" else None,
        categories=categories, default=None, step=None,
    )


# Dos vanos: VA con tres instancias, VB con una.
FEATURES = ["ALTURA", "TIPO", "prep_0", "prep_1"]
X_SEL = np.array([
    [8.0, 0.0, 1.0, 3.0],    # VA
    [12.0, 0.0, 5.0, 7.0],   # VA
    [10.0, 1.0, 2.0, 4.0],   # VA
    [30.0, 2.0, 9.0, 9.0],   # VB
])
INSTANCE_BAG = np.array([0, 0, 0, 1])
FIDS = ["VA", "VB"]


# --- Valores iniciales -------------------------------------------------------------------


def test_a_numeric_control_starts_at_the_vanos_own_median():
    """La MEDIANA y no la media: dentro de una ventana las instancias de un vano
    suelen incluir la hora del evento, que es justo la extrema, y una media
    arrancaria el control ya desplazado hacia ella."""
    valores = valores_actuales_por_vano(
        X_SEL, FEATURES, instance_bag=INSTANCE_BAG, fids=FIDS,
        knobs=[_knob("ALTURA")],
    )

    assert valores["VA"]["ALTURA"] == 10.0   # mediana de 8, 12, 10
    assert valores["VB"]["ALTURA"] == 30.0


def test_a_climate_family_starts_at_the_median_of_all_its_lags_pooled():
    """Un control climatico escribe UN valor en sus 12 rezagos a la vez, asi que
    su punto de partida tiene que resumir los 12 juntos. Tomar solo el rezago 0
    arrancaria el control en un numero que el propio control no puede sostener."""
    valores = valores_actuales_por_vano(
        X_SEL, FEATURES, instance_bag=INSTANCE_BAG, fids=FIDS,
        knobs=[_knob("clima:prep", feature_names=("prep_0", "prep_1"))],
    )

    # VA agrupa 1,5,2 y 3,7,4 -> mediana de los seis = 3.5
    assert valores["VA"]["clima:prep"] == 3.5
    assert valores["VB"]["clima:prep"] == 9.0


def test_a_categorical_control_starts_at_the_mode_decoded_to_its_label():
    """Una mediana sobre codigos de categoria puede caer en un codigo que no
    existe -- entre 'A'=0 y 'C'=2 devolveria 1, o sea 'B', una categoria que ese
    vano nunca tuvo. Se usa la MODA, y se devuelve la etiqueta y no el codigo,
    porque el control muestra etiquetas."""
    valores = valores_actuales_por_vano(
        X_SEL, FEATURES, instance_bag=INSTANCE_BAG, fids=FIDS,
        knobs=[_knob("TIPO", kind="categorical", categories=("A", "B", "C"))],
        label_encoders={"TIPO": _Encoder()},
    )

    assert valores["VA"]["TIPO"] == "A"   # codigos 0, 0, 1 -> moda 0
    assert valores["VB"]["TIPO"] == "C"   # codigo 2


def test_a_tie_in_the_mode_is_broken_by_the_lowest_code_so_it_is_reproducible():
    """Sin criterio de desempate el valor inicial cambiaria entre corridas, y un
    control que arranca distinto cada vez no permite comparar dos simulaciones."""
    X = np.array([[0.0], [2.0]])

    valores = valores_actuales_por_vano(
        X, ["TIPO"], instance_bag=np.array([0, 0]), fids=["VA"],
        knobs=[_knob("TIPO", kind="categorical", categories=("A", "B", "C"))],
        label_encoders={"TIPO": _Encoder()},
    )

    assert valores["VA"]["TIPO"] == "A"


def test_constant_knobs_get_no_starting_value():
    valores = valores_actuales_por_vano(
        X_SEL, FEATURES, instance_bag=INSTANCE_BAG, fids=FIDS,
        knobs=[_knob("ALTURA", kind="constant")],
    )

    assert valores == {"VA": {}, "VB": {}}


def test_a_knob_whose_feature_the_matrix_lacks_is_skipped_without_raising():
    """La matriz de instancias del MIL trae mas columnas que el catalogo de
    controles y podria traer menos: un desajuste no puede tumbar el arranque del
    panel entero."""
    valores = valores_actuales_por_vano(
        X_SEL, FEATURES, instance_bag=INSTANCE_BAG, fids=FIDS,
        knobs=[_knob("NO_ESTA"), _knob("ALTURA")],
    )

    assert set(valores["VA"]) == {"ALTURA"}


def test_an_empty_selection_yields_no_starting_values():
    valores = valores_actuales_por_vano(
        np.empty((0, 4)), FEATURES, instance_bag=np.array([], dtype=int), fids=[],
        knobs=[_knob("ALTURA")],
    )

    assert valores == {}


# --- Aplicacion de overrides por vano -----------------------------------------------------


def test_each_vano_only_receives_its_own_value():
    """El punto entero del cambio. Con la escritura broadcast anterior el ultimo
    vano pisaba a todos los demas y la simulacion contestaba por un escenario que
    nadie pidio."""
    X_sim, aplicadas, avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES,
        {"VA": [{"variable": "ALTURA", "valor": 20.0}],
         "VB": [{"variable": "ALTURA", "valor": 40.0}]},
        instance_bag=INSTANCE_BAG, fids=FIDS,
    )

    assert X_sim[:, 0].tolist() == [20.0, 20.0, 20.0, 40.0]
    assert aplicadas == ["ALTURA"]
    assert avisos == []
    # La matriz original NUNCA se toca: la comparte cada llamada posterior.
    assert X_SEL[0, 0] == 8.0


def test_a_vano_without_overrides_keeps_every_original_value():
    """Es lo que permite preguntar "que pasa si podo SOLO este": los demas vanos
    tienen que quedar exactamente como estaban, no en un valor por defecto."""
    X_sim, _aplicadas, _avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES, {"VA": [{"variable": "ALTURA", "valor": 20.0}]},
        instance_bag=INSTANCE_BAG, fids=FIDS,
    )

    assert X_sim[3].tolist() == X_SEL[3].tolist()


def test_a_climate_family_writes_the_same_value_into_every_lag_of_that_vano():
    X_sim, aplicadas, _avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES,
        {"VA": [{"variable": "prep_0", "valor": 30.0},
                {"variable": "prep_1", "valor": 30.0}]},
        instance_bag=INSTANCE_BAG, fids=FIDS,
    )

    assert X_sim[:3, 2].tolist() == [30.0, 30.0, 30.0]
    assert X_sim[:3, 3].tolist() == [30.0, 30.0, 30.0]
    assert X_sim[3, 2] == 9.0          # VB intacto
    assert aplicadas == ["prep_0", "prep_1"]


def test_a_categorical_value_goes_through_the_label_encoder():
    X_sim, aplicadas, _avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES, {"VB": [{"variable": "TIPO", "valor": "B"}]},
        instance_bag=INSTANCE_BAG, fids=FIDS,
        label_encoders={"TIPO": _Encoder()},
    )

    assert X_sim[3, 1] == 1.0
    assert aplicadas == ["TIPO"]


def test_an_unknown_variable_is_reported_and_the_rest_still_applies():
    """Misma politica que `aplicar_overrides_instancias`: un control roto no
    puede tirar una simulacion que el usuario esta esperando."""
    X_sim, aplicadas, avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES,
        {"VA": [{"variable": "NO_EXISTE", "valor": 1.0},
                {"variable": "ALTURA", "valor": 20.0}]},
        instance_bag=INSTANCE_BAG, fids=FIDS,
    )

    assert aplicadas == ["ALTURA"]
    assert len(avisos) == 1 and "NO_EXISTE" in avisos[0]
    assert X_sim[0, 0] == 20.0


def test_an_override_for_a_vano_outside_the_selection_is_reported():
    """Se puede quedar colgado de una seleccion anterior. Escribirlo en ningun
    lado en silencio haria que el panel muestre un control que no participo de
    la simulacion que devolvio."""
    _X_sim, aplicadas, avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES, {"VZ": [{"variable": "ALTURA", "valor": 20.0}]},
        instance_bag=INSTANCE_BAG, fids=FIDS,
    )

    assert aplicadas == []
    assert len(avisos) == 1 and "VZ" in avisos[0]


def test_no_overrides_at_all_returns_an_untouched_copy():
    X_sim, aplicadas, avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES, {}, instance_bag=INSTANCE_BAG, fids=FIDS,
    )

    assert np.array_equal(X_sim, X_SEL)
    assert (aplicadas, avisos) == ([], [])
    assert X_sim is not X_SEL


def test_the_applied_variables_are_reported_once_and_sorted():
    """Con cinco vanos la misma variable llega hasta cinco veces; el resumen del
    panel dice QUE se movio, no cuantas celdas se escribieron."""
    _X_sim, aplicadas, _avisos = aplicar_overrides_por_vano(
        X_SEL, FEATURES,
        {"VA": [{"variable": "prep_0", "valor": 1.0}, {"variable": "ALTURA", "valor": 2.0}],
         "VB": [{"variable": "ALTURA", "valor": 3.0}]},
        instance_bag=INSTANCE_BAG, fids=FIDS,
    )

    assert aplicadas == ["ALTURA", "prep_0"]


def test_the_same_vano_in_two_bags_receives_the_value_in_both():
    """Una seleccion es una sola ventana, asi que un fid deberia traer una bolsa.
    Si por lo que sea trae dos, escribir en una sola dejaria media simulacion
    silenciosamente sin aplicar."""
    X = np.array([[1.0], [1.0], [1.0]])

    X_sim, _aplicadas, _avisos = aplicar_overrides_por_vano(
        X, ["ALTURA"], {"VA": [{"variable": "ALTURA", "valor": 9.0}]},
        instance_bag=np.array([0, 1, 2]), fids=["VA", "VB", "VA"],
    )

    assert X_sim[:, 0].tolist() == [9.0, 1.0, 9.0]


# --- simular_bolsas con overrides por vano ------------------------------------------------


class _PredictorFalso:
    """u-hat es la media de la primera columna de cada bolsa: un override sobre
    esa columna mueve la clase de forma predecible."""

    def __init__(self):
        from chec_impacto.models.criticality_assignment import Geometria

        self.geometria = Geometria(
            logs=(False, False), offset=np.array([0.0, 0.0]), scale=np.array([1.0, 1.0]),
            centroides=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]),
        )
        self.llamadas = 0

    def predict(self, X_inst, instance_bag=None):
        self.llamadas += 1
        X_inst = np.asarray(X_inst, dtype=float)
        instance_bag = np.asarray(instance_bag)
        n_bags = int(instance_bag.max()) + 1 if instance_bag.size else 0
        return np.array([X_inst[instance_bag == b, 0].mean() for b in range(n_bags)])


def test_simular_bolsas_moves_each_vano_by_its_own_override():
    """La prueba que justifica todo el cambio: dos vanos, dos valores, y cada
    bolsa termina en el suyo. Con la escritura broadcast las dos habrian quedado
    en el mismo numero."""
    from chec_local_interpreter.mil_simulador_015 import simular_bolsas

    predictor = _PredictorFalso()
    X = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [3.0, 0.0]])
    seleccion = {"fid": ["VA", "VB"], "filas": np.array([0, 1, 2, 3]),
                 "instance_bag": np.array([0, 0, 0, 1]), "n_obs": np.array([3, 1]),
                 "n_bolsas": 2}

    tabla, meta = simular_bolsas(
        predictor, X, seleccion=seleccion, feature_names=["u_driver", "otra"],
        overrides_por_vano={"VA": [{"variable": "u_driver", "valor": 1.0}],
                            "VB": [{"variable": "u_driver", "valor": 2.0}]},
    )

    assert tabla["u_base"].tolist() == [0.0, 3.0]
    assert tabla["u_simulado"].tolist() == [1.0, 2.0]
    # sigue costando DOS pasadas y no una por vano
    assert predictor.llamadas == 2
    assert meta["variables_aplicadas"] == ["u_driver"]


def test_simular_bolsas_still_accepts_the_broadcast_overrides():
    """El camino viejo sigue vivo: un escenario climatico sobre toda la seleccion
    es una pregunta legitima y no tiene por que escribirse vano por vano."""
    from chec_local_interpreter.mil_simulador_015 import simular_bolsas

    predictor = _PredictorFalso()
    X = np.array([[0.0, 0.0], [3.0, 0.0]])
    seleccion = {"fid": ["VA", "VB"], "filas": np.array([0, 1]),
                 "instance_bag": np.array([0, 1]), "n_obs": np.array([1, 1]),
                 "n_bolsas": 2}

    tabla, _meta = simular_bolsas(
        predictor, X, seleccion=seleccion, feature_names=["u_driver", "otra"],
        overrides=[{"variable": "u_driver", "valor": 1.0}],
    )

    assert tabla["u_simulado"].tolist() == [1.0, 1.0]


def test_simular_bolsas_refuses_to_mix_both_override_shapes():
    """Aceptar las dos a la vez obliga a inventar una precedencia, y cualquiera
    que se elija deja al panel mostrando un control que no se aplico."""
    from chec_local_interpreter.mil_simulador_015 import simular_bolsas

    seleccion = {"fid": ["VA"], "filas": np.array([0]), "instance_bag": np.array([0]),
                 "n_obs": np.array([1]), "n_bolsas": 1}

    with pytest.raises(ValueError, match="por vano"):
        simular_bolsas(
            _PredictorFalso(), np.array([[0.0, 0.0]]), seleccion=seleccion,
            feature_names=["u_driver", "otra"],
            overrides=[{"variable": "u_driver", "valor": 1.0}],
            overrides_por_vano={"VA": [{"variable": "u_driver", "valor": 2.0}]},
        )


# --- Codigos de relleno en el valor inicial -----------------------------------------------


def test_the_starting_value_ignores_the_declared_filler_code():
    """`ALTURA` = 99 es "sin dato". Si la mediana del vano lo contara, el control
    abriria en 99, que ya ni siquiera esta dentro de sus propios limites -- y el
    panel lo recortaria al maximo en silencio, mostrando una altura que ese vano
    nunca tuvo como si fuera su valor actual."""
    X = np.array([[10.0], [99.0], [12.0]])

    valores = valores_actuales_por_vano(
        X, ["ALTURA"], instance_bag=np.array([0, 0, 0]), fids=["VA"],
        knobs=[_knob("ALTURA", feature_names=("ALTURA",))],
    )

    assert valores["VA"]["ALTURA"] == 11.0   # mediana de 10 y 12, sin el 99


def test_a_vano_whose_value_is_only_filler_gets_no_starting_value():
    """No hay valor actual que mostrar. Se omite la clave en vez de inventar uno:
    el panel puede entonces decirlo, que es distinto de abrir el control en un
    numero que nadie midio."""
    X = np.array([[99.0], [99.0]])

    valores = valores_actuales_por_vano(
        X, ["ALTURA"], instance_bag=np.array([0, 0]), fids=["VA"],
        knobs=[_knob("ALTURA", feature_names=("ALTURA",))],
    )

    assert "ALTURA" not in valores["VA"]


def test_other_variables_are_untouched_by_the_filler_rule():
    X = np.array([[99.0], [7.0]])

    valores = valores_actuales_por_vano(
        X, ["LONG_CRUCETA"], instance_bag=np.array([0, 0]), fids=["VA"],
        knobs=[_knob("LONG_CRUCETA", feature_names=("LONG_CRUCETA",))],
    )

    assert valores["VA"]["LONG_CRUCETA"] == 53.0   # mediana de 99 y 7, sin filtrar
