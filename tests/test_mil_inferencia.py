"""RED/GREEN tests for `mil_inferencia`: the report's predictive layer on the
MIL bag model of notebook 05, replacing the MGCECDL row-level path.

The unit changed, and that is the whole point. MGCECDL scored one ROW; the MIL
model scores a BAG -- one (vano, ventana) cell -- which is the unit notebook 04
defines criticality on and the unit notebook 06's simulator moves. A report built
on rows and a dashboard built on bags answered the same question with two models
and no way to reconcile them.

Everything here is measured on UITI: `relevancia_hacia_uiti_minimo` ranks how far
each control can pull a bag's predicted UITI down. Event count never enters this
layer -- it is descriptive and belongs to the historian.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chec_local_interpreter.mil_inferencia import (
    RecursosMIL,
    diagnostico_de_circuito,
    escenarios_de_circuito,
    relevancia_de_circuito,
    resumen_de_modelo,
    ventanas_de_circuito,
)


class _BagIndexFalso:
    def __init__(self, keys, offsets, counts):
        self.keys = keys
        self.offsets = np.asarray(offsets, dtype=np.int64)
        self.counts = np.asarray(counts, dtype=np.int64)


class _PredictorFalso:
    """u-hat es la media de la primera columna de la bolsa, asi que bajar esa
    columna baja el UITI predicho de forma comprobable."""

    def __init__(self, geometria):
        self.geometria = geometria
        self.llamadas = 0

    def predict(self, X_inst, instance_bag=None):
        self.llamadas += 1
        X_inst = np.asarray(X_inst, dtype=float)
        if instance_bag is None:
            return X_inst[:, 0]
        instance_bag = np.asarray(instance_bag)
        n = int(instance_bag.max()) + 1 if instance_bag.size else 0
        return np.array([X_inst[instance_bag == b, 0].mean() for b in range(n)])


def _geometria():
    from chec_impacto.models.criticality_assignment import Geometria

    return Geometria(
        logs=(False, False),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]),
    )


def _knob(knob_id, bounds=(0.0, 4.0)):
    from chec_local_interpreter.vano_controls import Knob

    return Knob(id=knob_id, label=knob_id, kind="numeric",
                feature_names=(knob_id,), bounds=bounds, categories=None,
                default=None, step=None)


def _recursos():
    """Dos vanos de un circuito en una ventana: uno tranquilo y uno critico."""
    X = np.array([[0.0, 1.0], [0.0, 1.0], [3.0, 1.0], [3.0, 1.0]], dtype=np.float32)
    # `keys` es un DataFrame en el artefacto real, con una fila por bolsa.
    bag_index = _BagIndexFalso(
        keys=pd.DataFrame({"CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V2"],
                           "VENTANA": ["W1", "W1"]}),
        offsets=[0, 2, 4],
        counts=[2, 2],
    )
    return RecursosMIL(
        modelo=_PredictorFalso(_geometria()),
        X_inst=X,
        features=["u_driver", "otra"],
        bag_index=bag_index,
        knobs=[_knob("u_driver")],
        label_encoders={},
        max_values_imputed={},
    )


def test_relevance_is_measured_on_uiti_and_never_on_event_count():
    """El modelo predice UITI acumulado. El conteo de eventos es un eje del espacio
    KMeans que define la clase, no una salida del modelo: pedirle que lo explique
    seria pedirle una magnitud que no produce."""
    recursos = _recursos()

    resultado = relevancia_de_circuito(recursos, circuito="C1", ventana="W1")

    assert resultado["metrica"] == "uiti_acumulado"
    assert resultado["vanos"], "un circuito con bolsas tiene que producir relevancia"
    for entrada in resultado["vanos"].values():
        for variable in entrada["variables"]:
            assert {"knob_id", "u_base", "u_min", "caida"} <= set(variable)
            assert "eventos" not in variable and "n_obs" not in variable


def test_relevance_on_a_circuit_with_no_bags_is_empty_not_an_error():
    """Un circuito sin bolsas en la ventana es un caso normal -- hay circuitos con
    una sola ventana con eventos en todo el ano --, no un fallo del reporte."""
    recursos = _recursos()

    resultado = relevancia_de_circuito(recursos, circuito="NO_EXISTE", ventana="W1")

    assert resultado["vanos"] == {}
    assert resultado["metrica"] == "uiti_acumulado"


def test_the_diagnosis_ranks_the_critical_vanos_and_carries_their_plan():
    """Los vanos criticos ya no salen de un percentil de UITI promedio sino del
    diagnostico del cuaderno 06: el plan que lleva cada bolsa hacia su clase minima,
    mirando primero el grupo Alto y completando con Medio-Alto."""
    recursos = _recursos()

    criticos = diagnostico_de_circuito(recursos, circuito="C1", ventana="W1", top=5)

    assert criticos, "el vano en clase alta tiene que aparecer"
    primero = criticos[0]
    assert {"fid", "clase_base", "u_base", "pasos", "alcanza"} <= set(primero)
    # Ordenado por criticidad: el vano de u=3 va antes que el de u=0.
    assert primero["fid"] == "V2"
    assert all(isinstance(paso.get("knob_id"), str) for paso in primero["pasos"])


def test_the_diagnosis_never_reports_more_vanos_than_asked():
    recursos = _recursos()

    assert len(diagnostico_de_circuito(recursos, circuito="C1", ventana="W1", top=1)) == 1


def test_the_model_summary_names_the_bag_unit_not_the_row():
    """Lo que el informe imprime sobre el modelo tiene que decir en que unidad
    trabaja: es la diferencia entre 'la variable X pesa en este circuito' y 'la
    variable X pesa en esta celda vano-ventana'."""
    recursos = _recursos()

    resumen = resumen_de_modelo(recursos)

    assert resumen["unidad"] == "bolsa (vano, ventana)"
    assert resumen["objetivo"] == "uiti_acumulado"
    assert resumen["n_bolsas"] == 2
    assert "mgcecdl" not in str(resumen).lower()


def test_the_diagnosis_returns_nothing_when_no_vano_reaches_a_critical_group():
    """Sin vanos en Alto ni Medio-Alto la respuesta correcta es "ninguno", no los
    menos malos. Devolver los de Medio bajo el rotulo de diagnostico convierte
    "este circuito esta tranquilo esta ventana" en una orden de trabajo inventada.
    """
    recursos = _recursos()
    # Las dos bolsas quedan en las clases bajas: u = 0 en ambos vanos.
    recursos.X_inst = np.zeros_like(recursos.X_inst)

    criticos = diagnostico_de_circuito(recursos, circuito="C1", ventana="W1", top=5)

    assert criticos == []


def test_relevance_says_when_it_ran_without_controls():
    """El barrido recorre los CONTROLES; sin catalogo devuelve vanos con la lista de
    variables vacia, que se lee como "ninguna variable mueve este vano" cuando en
    realidad es "no se le paso el catalogo". Se declara en el resultado."""
    recursos = _recursos()
    recursos.knobs = []

    resultado = relevancia_de_circuito(recursos, circuito="C1", ventana="W1")

    assert resultado["n_controles"] == 0
    assert resultado["sin_controles"] is True


# --- Los escenarios, que con el MIL son VENTANAS -----------------------------------------


def test_scenarios_are_windows_because_that_is_what_a_bag_is():
    """Con MGCECDL un escenario era un percentil de filas; con el MIL la unidad es la
    bolsa (vano, ventana), asi que el escenario natural es la VENTANA. Mantener el
    percentil habria dejado el informe hablando de una particion que el modelo no ve.
    """
    recursos = _recursos()

    escenarios = escenarios_de_circuito(recursos, circuito="C1")

    assert escenarios, "un circuito con bolsas tiene al menos un escenario"
    uno = escenarios[0]
    assert uno["ventana"] == "W1"
    assert uno["metrica"] == "uiti_acumulado"
    assert {"nombre", "ventana", "relevancia", "vanos_criticos"} <= set(uno)


def test_scenarios_are_restricted_to_the_windows_asked_for():
    recursos = _recursos()

    assert escenarios_de_circuito(recursos, circuito="C1", ventanas=["W9"]) == []
    assert len(escenarios_de_circuito(recursos, circuito="C1", ventanas=["W1"])) == 1


def test_ventanas_de_circuito_lists_only_the_windows_that_circuit_has():
    """Un circuito tranquilo puede no tener bolsas en media parte del ano. Ofrecer
    ventanas que ese circuito no tiene produce escenarios vacios que el informe
    presenta como si el modelo no hubiera encontrado nada."""
    recursos = _recursos()

    assert ventanas_de_circuito(recursos, circuito="C1") == ["W1"]
    assert ventanas_de_circuito(recursos, circuito="NO_EXISTE") == []
