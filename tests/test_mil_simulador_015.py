"""RED/GREEN tests for `mil_simulador_015`: notebook 06's bag-level
simulation on the MIL model trained in notebook 05, plus the reconstructed
expert graph for the active selection.

The MIL model scores BAGS, not rows: one bag is one (vano, ventana) cell,
and its criticality class comes from `asignar_clase(OBSERVED n_obs,
predicted u-hat)`. Feeding it one row per bag with `n_obs = 1` -- the
per-row contract `mil_vano_ventana.predict_fn` pins for SHAP -- would move
every vano along the `n_obs` axis of the very KMeans space that defines the
class, so this module never uses that path.

The MIL instance matrix is RAW model space (no min-max scaler), unlike
`simulator.simulate_explicit_overrides`'s input, so an override is written
straight into the column after `_coerce_original_value_for_model` resolves
categories and dates.

See:
  - `chec_impacto/interpretability/mil_vano_ventana.py` (`BagPredictor`)
  - `chec_impacto/data/bags.py` (`BagIndex`, CSR instance layout)
  - `chec_impacto/interpretability/mgcecdl_graph.py`
    (`grafo_reconstruido_por_grupo`)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chec_impacto.models.criticality_assignment import Geometria
from chec_local_interpreter.mil_simulador_015 import (
    aplicar_overrides_instancias,
    grafo_de_gates,
    grafo_diferencia,
    seleccionar_bolsas,
    simular_bolsas,
    trazas_grafo,
)


class _BagIndexFalso:
    """The three `BagIndex` fields this module reads. The real dataclass
    validates a full CSR layout; these tests only need its shape."""

    def __init__(self, keys, offsets, counts):
        self.keys = keys
        self.offsets = np.asarray(offsets, dtype=np.int64)
        self.counts = np.asarray(counts, dtype=np.int64)


def _bag_index():
    keys = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2"],
            "FID_VANO": ["VA", "VA", "VB", "VZ"],
            "VENTANA": ["V1", "V2", "V1", "V1"],
        }
    )
    #        bolsa 0: 2 filas | bolsa 1: 1 fila | bolsa 2: 3 filas | bolsa 3: 1 fila
    counts = [2, 1, 3, 1]
    offsets = np.concatenate([[0], np.cumsum(counts)])
    return _BagIndexFalso(keys, offsets, counts)


# --- Seleccion de bolsas ------------------------------------------------------------------


def test_seleccionar_bolsas_takes_the_marked_vanos_of_one_circuit_and_window():
    seleccion = seleccionar_bolsas(_bag_index(), circuito="C1", ventana="V1", marcados=["VB"])

    assert seleccion["fid"] == ["VB"]
    assert seleccion["filas"].tolist() == [3, 4, 5]  # las 3 instancias de la bolsa 2
    assert seleccion["instance_bag"].tolist() == [0, 0, 0]  # renumerada desde 0
    assert seleccion["n_obs"].tolist() == [3]
    assert seleccion["n_bolsas"] == 1


def test_seleccionar_bolsas_without_marked_vanos_takes_the_whole_circuit_window():
    """Mismo criterio que el resto del cuaderno: sin vanos marcados el grano es el
    circuito completo en esa ventana."""
    seleccion = seleccionar_bolsas(_bag_index(), circuito="C1", ventana="V1")

    assert seleccion["fid"] == ["VA", "VB"]
    assert seleccion["filas"].tolist() == [0, 1, 3, 4, 5]
    assert seleccion["instance_bag"].tolist() == [0, 0, 1, 1, 1]
    assert seleccion["n_obs"].tolist() == [2, 3]


def test_seleccionar_bolsas_returns_an_explicit_empty_selection():
    seleccion = seleccionar_bolsas(_bag_index(), circuito="C1", ventana="V9")

    assert seleccion["n_bolsas"] == 0
    assert seleccion["fid"] == []
    assert seleccion["filas"].tolist() == []


def test_seleccionar_bolsas_matches_string_fids_against_a_numeric_column():
    """Regresion conocida de este proyecto: los fids del mapa son STRINGS y la
    columna puede venir numerica. Sin coercion no coincide ninguno."""
    bag_index = _bag_index()
    bag_index.keys["FID_VANO"] = [20130434, 20130434, 20130436, 20130440]

    seleccion = seleccionar_bolsas(bag_index, circuito="C1", ventana="V1",
                                   marcados=["20130436"])

    assert seleccion["fid"] == ["20130436"]


# --- Overrides sobre el espacio RAW de instancias -----------------------------------------


def test_aplicar_overrides_writes_the_raw_value_into_its_column():
    X = np.array([[1.0, 2.0], [3.0, 4.0]])

    X_sim, aplicadas, avisos = aplicar_overrides_instancias(
        X, ["LONGITUD", "ALTURA"], [{"variable": "ALTURA", "valor": 9.5}]
    )

    assert X_sim[:, 1].tolist() == [9.5, 9.5]  # se difunde a TODAS las instancias
    assert X_sim[:, 0].tolist() == [1.0, 3.0]  # la otra columna intacta
    assert aplicadas == ["ALTURA"] and avisos == []
    assert X[:, 1].tolist() == [2.0, 4.0]  # la entrada nunca se muta


def test_aplicar_overrides_records_an_unknown_variable_instead_of_raising():
    """Misma politica que `simulate_explicit_overrides`: una variable que falla no
    tumba la simulacion entera, se reporta y las demas se aplican igual."""
    X = np.array([[1.0, 2.0]])

    X_sim, aplicadas, avisos = aplicar_overrides_instancias(
        X, ["LONGITUD", "ALTURA"],
        [{"variable": "NO_EXISTE", "valor": 1}, {"variable": "ALTURA", "valor": 7.0}],
    )

    assert aplicadas == ["ALTURA"]
    assert len(avisos) == 1 and "NO_EXISTE" in avisos[0]
    assert X_sim[:, 1].tolist() == [7.0]


def test_aplicar_overrides_encodes_a_categorical_through_its_label_encoder():
    class _Encoder:
        classes_ = np.array(["A", "B", "C"])

        def transform(self, valores):
            return np.array([list(self.classes_).index(v) for v in valores])

    X = np.array([[0.0, 0.0]])

    X_sim, aplicadas, _avisos = aplicar_overrides_instancias(
        X, ["TIPO", "ALTURA"], [{"variable": "TIPO", "valor": "C"}],
        label_encoders={"TIPO": _Encoder()},
    )

    assert X_sim[0, 0] == 2.0
    assert aplicadas == ["TIPO"]


# --- Simulacion a nivel de bolsa ----------------------------------------------------------


def _geometria():
    """Cuatro centroides sobre la diagonal en un espacio sin logs ni escala: la
    clase de una bolsa es el entero mas cercano a (n_obs, u) proyectado."""
    return Geometria(
        logs=(False, False),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]),
    )


class _PredictorFalso:
    """Un `BagPredictor` sin torch: u-hat es la media de la primera columna de
    cada bolsa, asi un override sobre esa columna mueve la clase de forma
    predecible."""

    def __init__(self, geometria):
        self.geometria = geometria
        self.llamadas = 0

    def predict(self, X_inst, instance_bag=None):
        self.llamadas += 1
        X_inst = np.asarray(X_inst, dtype=float)
        if instance_bag is None:
            return X_inst[:, 0]
        instance_bag = np.asarray(instance_bag)
        n_bags = int(instance_bag.max()) + 1 if instance_bag.size else 0
        return np.array([X_inst[instance_bag == b, 0].mean() for b in range(n_bags)])


def test_simular_bolsas_returns_base_and_simulated_class_per_vano():
    predictor = _PredictorFalso(_geometria())
    X = np.array([[0.0, 0.0], [0.0, 0.0], [3.0, 0.0], [3.0, 0.0], [3.0, 0.0]])
    seleccion = {
        "fid": ["VA", "VB"],
        "filas": np.array([0, 1, 2, 3, 4]),
        "instance_bag": np.array([0, 0, 1, 1, 1]),
        "n_obs": np.array([2, 3]),
        "n_bolsas": 2,
    }

    tabla, meta = simular_bolsas(
        predictor, X, seleccion=seleccion, feature_names=["u_driver", "otra"],
        overrides=[{"variable": "u_driver", "valor": 1.0}],
    )

    assert list(tabla["FID_VANO"]) == ["VA", "VB"]
    assert list(tabla.columns) >= ["FID_VANO", "base_clase_idx", "simulado_clase_idx"]
    # base: u = 0 y 3 -> el override lleva las dos bolsas a u = 1
    assert tabla["u_base"].tolist() == [0.0, 3.0]
    assert tabla["u_simulado"].tolist() == [1.0, 1.0]
    # exactamente DOS pasadas: base y simulado, nunca una por vano
    assert predictor.llamadas == 2
    assert meta["n_vanos"] == 2 and meta["n_instancias"] == 5
    assert meta["variables_aplicadas"] == ["u_driver"]


def test_simular_bolsas_uses_the_observed_n_obs_never_a_predicted_one():
    """`n_obs` es un EJE del espacio KMeans que define la clase. Si la simulacion
    lo tocara, el vano se moveria por un eje que el modelo no predice."""
    predictor = _PredictorFalso(_geometria())
    X = np.array([[3.0, 0.0]] * 3)
    seleccion = {"fid": ["VA"], "filas": np.array([0, 1, 2]),
                 "instance_bag": np.array([0, 0, 0]), "n_obs": np.array([3]),
                 "n_bolsas": 1}

    tabla, _meta = simular_bolsas(predictor, X, seleccion=seleccion,
                                  feature_names=["u_driver", "otra"], overrides=[])

    # (n_obs=3, u=3) cae exactamente sobre el centroide 3
    assert tabla["base_clase_idx"].tolist() == [3]
    assert tabla["simulado_clase_idx"].tolist() == [3]
    assert tabla["delta_riesgo_ordinal"].tolist() == [0]


def test_simular_bolsas_on_an_empty_selection_returns_an_empty_table():
    predictor = _PredictorFalso(_geometria())
    seleccion = {"fid": [], "filas": np.array([], dtype=int),
                 "instance_bag": np.array([], dtype=int),
                 "n_obs": np.array([], dtype=int), "n_bolsas": 0}

    tabla, meta = simular_bolsas(predictor, np.zeros((0, 2)), seleccion=seleccion,
                                 feature_names=["a", "b"], overrides=[])

    assert tabla.empty and meta["n_vanos"] == 0
    assert predictor.llamadas == 0  # ni una pasada del modelo sobre nada


# --- Grafo reconstruido de la seleccion ---------------------------------------------------


class _EdgeIndexFalso:
    def __init__(self, pairs, weights):
        self.pairs = np.asarray(pairs, dtype=np.int64)
        self.weights = np.asarray(weights, dtype=float)
        self.n_edges = len(self.weights)


def test_grafo_de_gates_reconstructs_one_mean_graph_for_the_whole_selection():
    """El panel muestra UN grafo -- el de la seleccion completa -- y no uno por
    grupo de criticidad: se obtiene pasando una sola etiqueta a la funcion ya
    probada de `mgcecdl_graph`, sin matematica nueva aca."""
    edge_index = _EdgeIndexFalso(pairs=[[0, 1], [1, 2]], weights=[2.0, 4.0])
    gates = np.array([[0.5, 1.0], [1.5, 3.0], [1.0, 1.0]])  # 3 vanos, 2 aristas

    grafo = grafo_de_gates(gates, edge_index, n_features=3)

    assert grafo["voided"] is False
    assert grafo["n_vanos"] == 3
    # peso = media_vanos(gate) * peso_fijo -> arista 0: 1.0*2.0, arista 1: (5/3)*4.0
    assert grafo["matriz"][0, 1] == pytest.approx(2.0)
    assert grafo["matriz"][1, 2] == pytest.approx(4.0 * 5.0 / 3.0)
    assert grafo["matriz"][2, 0] == 0.0  # fuera del soporte del edge index


@pytest.mark.parametrize("n_vanos", [1, 2])
def test_grafo_de_gates_is_voided_below_three_vanos(n_vanos):
    """Limite REAL de `estadistico_colapso`, no una decision de este modulo: su
    veredicto incluye `effective_rank <= 1`, y la matriz centrada de una o dos
    filas tiene rango 1 por construccion. Con menos de 3 vanos marcados el panel
    no puede mostrar un grafo por seleccion, y decirlo es lo correcto -- dibujar
    el grafo experto fijo ahi lo haria pasar por estructura estimada."""
    edge_index = _EdgeIndexFalso(pairs=[[0, 1], [1, 2]], weights=[2.0, 4.0])
    gates = np.array([[0.5, 1.0], [1.5, 3.0]])[:n_vanos]

    assert grafo_de_gates(gates, edge_index, n_features=3)["voided"] is True


def test_grafo_de_gates_reports_a_collapsed_gate_instead_of_a_graph():
    """A4: una matriz de compuertas colapsada ANULA el grafo. Dibujar igual seria
    presentar como estructura por seleccion algo que no depende de ella."""
    edge_index = _EdgeIndexFalso(pairs=[[0, 1], [1, 2]], weights=[2.0, 4.0])
    gates = np.repeat(np.array([[1.0, 1.0]]), 5, axis=0)  # identicas: colapso

    grafo = grafo_de_gates(gates, edge_index, n_features=3)

    assert grafo["voided"] is True
    assert grafo["matriz"] is None


def test_grafo_de_gates_on_an_empty_selection_is_voided_without_calling_the_math():
    grafo = grafo_de_gates(np.zeros((0, 2)), _EdgeIndexFalso([[0, 1], [1, 2]], [1.0, 1.0]),
                           n_features=3)

    assert grafo["voided"] is True and grafo["matriz"] is None


# --- Trazas del grafo ---------------------------------------------------------------------


def test_trazas_grafo_lays_out_only_the_features_that_participate_in_an_edge():
    matriz = np.zeros((4, 4))
    matriz[0, 2] = 1.0  # solo 0 y 2 tienen arista; 1 y 3 quedan fuera del dibujo

    trazas = trazas_grafo(matriz, ["A", "B", "C", "D"])

    assert trazas["nodos"]["texto"] == ["A", "C"]
    assert len(trazas["nodos"]["x"]) == 2
    # El indice de la columna viaja con el nodo: es lo que deja al cuaderno colorear
    # cada variable por su MODALIDAD sin volver a buscar el nombre en la lista.
    assert trazas["nodos"]["indice"] == [0, 2]
    # una arista = 3 slots (origen, destino, None) para que Plotly corte la linea
    assert len(trazas["aristas"]["x"]) == 3 and trazas["aristas"]["x"][2] is None
    assert trazas["pesos"]["peso"] == [1.0]
    assert len(trazas["pesos"]["x"]) == 1  # un punto por arista, en su punto medio


def test_trazas_grafo_is_empty_for_a_graph_with_no_edges():
    trazas = trazas_grafo(np.zeros((3, 3)), ["A", "B", "C"])

    assert trazas["nodos"]["x"] == [] and trazas["aristas"]["x"] == []
    assert trazas["pesos"]["peso"] == []


def test_trazas_grafo_hovertext_names_both_ends_and_the_weight():
    matriz = np.zeros((2, 2))
    matriz[1, 0] = 0.25

    trazas = trazas_grafo(matriz, ["ALTURA", "DDT"])

    assert "DDT" in trazas["pesos"]["hovertext"][0]
    assert "ALTURA" in trazas["pesos"]["hovertext"][0]
    assert "0.25" in trazas["pesos"]["hovertext"][0]


# --- Sensibilidad min-max a nivel de bolsa (panel "Importancia Variables") ----------------


def _knobs_numericos():
    from chec_local_interpreter.vano_controls import Knob

    return [
        Knob(id="u_driver", label="u_driver", kind="numeric", feature_names=("u_driver",),
             bounds=(0.0, 4.0), categories=None, default=2.0, step=0.1),
        Knob(id="otra", label="otra", kind="numeric", feature_names=("otra",),
             bounds=(0.0, 1.0), categories=None, default=0.5, step=0.1),
        Knob(id="TIPO", label="TIPO", kind="categorical", feature_names=("TIPO",),
             bounds=None, categories=("A", "B"), default="A", step=None),
    ]


def _seleccion_dos_bolsas():
    return {
        "fid": ["VA", "VB"],
        "filas": np.array([0, 1, 2]),
        "instance_bag": np.array([0, 0, 1]),
        "n_obs": np.array([2, 1]),
        "n_bolsas": 2,
    }


def test_sensibilidad_minmax_ranks_the_variable_that_moves_the_prediction():
    """El barrido pasa a la MISMA unidad que el simulador: la bolsa. `u_driver` mueve
    la prediccion entre su minimo y su maximo; `otra` no toca nada, asi que su
    magnitud tiene que ser cero y quedar abajo."""
    from chec_local_interpreter.mil_simulador_015 import sensibilidad_minmax_bolsas

    predictor = _PredictorFalso(_geometria())
    X = np.array([[1.0, 0.3], [1.0, 0.4], [1.0, 0.5]])

    filas, meta = sensibilidad_minmax_bolsas(
        predictor, X, seleccion=_seleccion_dos_bolsas(),
        feature_names=["u_driver", "otra"], knobs=_knobs_numericos(),
    )

    assert [f["knob_id"] for f in filas] == ["u_driver", "otra"]  # ordenado descendente
    assert filas[0]["magnitud_max_cambio_abs"] > 0.0
    assert filas[1]["magnitud_max_cambio_abs"] == pytest.approx(0.0)
    assert meta["n_vanos"] == 2 and meta["n_instancias"] == 3


def test_sensibilidad_minmax_skips_knobs_without_numeric_bounds():
    """Los knobs categoricos y constantes no tienen minimo/maximo numerico: se omiten,
    igual que hace el barrido de MGCECDL. Inventarles un rango seria puntuar un
    escenario que nunca se pidio."""
    from chec_local_interpreter.mil_simulador_015 import sensibilidad_minmax_bolsas

    predictor = _PredictorFalso(_geometria())
    X = np.array([[1.0, 0.3], [1.0, 0.4], [1.0, 0.5]])

    filas, _meta = sensibilidad_minmax_bolsas(
        predictor, X, seleccion=_seleccion_dos_bolsas(),
        feature_names=["u_driver", "otra"], knobs=_knobs_numericos(),
    )

    assert "TIPO" not in {f["knob_id"] for f in filas}


def test_sensibilidad_minmax_costs_two_passes_per_knob_plus_one_baseline():
    """Presupuesto explicito: 2 pasadas por knob numerico mas UNA de base compartida.
    Si alguna vez se recalcula la base por variable, esto lo cachea."""
    from chec_local_interpreter.mil_simulador_015 import sensibilidad_minmax_bolsas

    predictor = _PredictorFalso(_geometria())
    X = np.array([[1.0, 0.3], [1.0, 0.4], [1.0, 0.5]])

    sensibilidad_minmax_bolsas(
        predictor, X, seleccion=_seleccion_dos_bolsas(),
        feature_names=["u_driver", "otra"], knobs=_knobs_numericos(),
    )

    assert predictor.llamadas == 1 + 2 * 2  # base + (min, max) x 2 knobs numericos


def test_sensibilidad_minmax_on_an_empty_selection_returns_nothing():
    from chec_local_interpreter.mil_simulador_015 import sensibilidad_minmax_bolsas

    predictor = _PredictorFalso(_geometria())
    seleccion = {"fid": [], "filas": np.array([], dtype=int),
                 "instance_bag": np.array([], dtype=int),
                 "n_obs": np.array([], dtype=int), "n_bolsas": 0}

    filas, meta = sensibilidad_minmax_bolsas(
        predictor, np.zeros((0, 2)), seleccion=seleccion,
        feature_names=["u_driver", "otra"], knobs=_knobs_numericos(),
    )

    assert filas == [] and meta["n_vanos"] == 0
    assert predictor.llamadas == 0


def test_relevance_cache_mil_normalises_with_softmax_and_memoises():
    from chec_local_interpreter.mil_simulador_015 import construir_relevance_cache_mil

    predictor = _PredictorFalso(_geometria())
    X = np.array([[1.0, 0.3], [1.0, 0.4], [1.0, 0.5], [2.0, 0.6]])
    bag_index = _BagIndexFalso(
        pd.DataFrame({"CIRCUITO": ["C1", "C1"], "FID_VANO": ["VA", "VB"],
                      "VENTANA": ["V1", "V1"]}),
        offsets=[0, 2, 4], counts=[2, 2],
    )

    rankear = construir_relevance_cache_mil(
        predictor=predictor, X_inst=X, bag_index=bag_index,
        feature_names=["u_driver", "otra"], knobs=_knobs_numericos(),
    )
    resultado = rankear("C1", "V1", [])
    llamadas_primera = predictor.llamadas

    assert resultado["vacio"] is False
    assert sum(f["relevancia"] for f in resultado["filas"]) == pytest.approx(1.0)
    assert resultado["n_vanos"] == 2

    rankear("C1", "V1", [])  # misma clave -> servido del LRU, sin pasadas nuevas
    assert predictor.llamadas == llamadas_primera


def test_relevance_cache_mil_reports_an_empty_selection_explicitly():
    from chec_local_interpreter.mil_simulador_015 import construir_relevance_cache_mil

    predictor = _PredictorFalso(_geometria())
    bag_index = _BagIndexFalso(
        pd.DataFrame({"CIRCUITO": ["C1"], "FID_VANO": ["VA"], "VENTANA": ["V1"]}),
        offsets=[0, 1], counts=[1],
    )

    rankear = construir_relevance_cache_mil(
        predictor=predictor, X_inst=np.array([[1.0, 0.3]]), bag_index=bag_index,
        feature_names=["u_driver", "otra"], knobs=_knobs_numericos(),
    )
    resultado = rankear("C1", "V9", [])

    assert resultado["vacio"] is True and resultado["filas"] == []
    assert resultado["mensaje"]
    assert predictor.llamadas == 0


# --- El grafo de la ultima fila: lo que la simulacion le HIZO al grafo ------------------


def test_grafo_diferencia_is_the_absolute_change_the_simulation_produced():
    """El panel de la ultima fila ya no muestra el grafo de la seleccion sino
    `|grafo_base - grafo_simulado|`: cuanto movio la simulacion cada relacion.

    El grafo base y el simulado se parecen mucho -- comparten los pesos fijos del
    experto y solo cambian por las compuertas --, asi que puestos uno al lado del
    otro se ven iguales y la diferencia se pierde. En valor ABSOLUTO porque la
    pregunta es cuanto se movio la relacion, no en que direccion: una arista que
    baja y otra que sube importan lo mismo para saber que toco la intervencion."""
    edge_index = _EdgeIndexFalso(pairs=[[0, 1], [1, 2]], weights=[2.0, 4.0])
    gates_base = np.array([[0.5, 1.0], [1.5, 3.0], [1.0, 1.0]])
    gates_sim = np.array([[0.5, 0.5], [1.5, 1.0], [1.0, 0.5]])

    grafo = grafo_diferencia(gates_base, gates_sim, edge_index, n_features=3)

    assert grafo["voided"] is False
    assert grafo["n_vanos"] == 3
    # La arista 0 no cambio de compuertas: su diferencia es exactamente cero.
    assert grafo["matriz"][0, 1] == pytest.approx(0.0)
    # La arista 1: media base 5/3, media simulada 2/3, por el peso fijo 4.
    assert grafo["matriz"][1, 2] == pytest.approx(4.0 * (5.0 / 3.0 - 2.0 / 3.0))


def test_grafo_diferencia_is_absolute_and_never_signed():
    """Una arista que la simulacion SUBE pesa lo mismo que una que baja: las dos
    dicen que la intervencion toco esa relacion."""
    # DOS aristas que varian de forma independiente entre vanos. Con una sola, el
    # `effective_rank` vale 1 por construccion y `estadistico_colapso` anula siempre,
    # asi que el test no llegaria a mirar el signo.
    edge_index = _EdgeIndexFalso(pairs=[[0, 1], [1, 2]], weights=[1.0, 1.0])
    gates_base = np.array([[1.0, 5.0], [2.0, 1.0], [3.0, 3.0]])   # arista 0: media 2.0
    gates_sim = np.array([[3.0, 1.0], [4.0, 4.0], [5.0, 4.0]])    # arista 0: media 4.0

    grafo = grafo_diferencia(gates_base, gates_sim, edge_index, n_features=3)

    # Subio de 2,0 a 4,0 y el panel lo reporta como 2,0, igual que si hubiera bajado.
    assert grafo["matriz"][0, 1] == pytest.approx(2.0)


def test_grafo_diferencia_is_voided_when_either_side_is():
    """Si el grafo base no es estimable, su diferencia tampoco: restar contra algo
    que no se pudo estimar produciria una matriz que parece un resultado. Con menos
    de 3 vanos `estadistico_colapso` anula, y la diferencia hereda esa anulacion."""
    edge_index = _EdgeIndexFalso(pairs=[[0, 1], [1, 2]], weights=[2.0, 4.0])
    gates = np.array([[0.5, 1.0], [1.5, 3.0]])  # 2 vanos: anulado por construccion

    grafo = grafo_diferencia(gates, gates, edge_index, n_features=3)

    assert grafo["voided"] is True
    assert grafo["matriz"] is None


def test_grafo_diferencia_of_a_simulation_that_changed_nothing_is_all_zeros():
    """Sin overrides el grafo simulado es el mismo que el base. La matriz sale toda
    en cero, que es un resultado y no un panel roto: dice que la intervencion no
    movio ninguna relacion."""
    edge_index = _EdgeIndexFalso(pairs=[[0, 1], [1, 2]], weights=[2.0, 4.0])
    gates = np.array([[0.5, 1.0], [1.5, 3.0], [1.0, 1.0]])

    grafo = grafo_diferencia(gates, gates, edge_index, n_features=3)

    assert grafo["voided"] is False
    assert float(np.abs(grafo["matriz"]).max()) == pytest.approx(0.0)


def test_simular_bolsas_hands_back_the_simulated_matrix():
    """El grafo de la ultima fila necesita las features SIMULADAS para estimar su
    lado del `|base - simulado|`. Salen por la metadata en vez de rearmarse en el
    cuaderno: repetir ahi la expansion de overrides es la forma segura de que el
    grafo acabe describiendo un escenario distinto del que puntuo el mapa."""
    predictor = _PredictorFalso(_geometria())
    seleccion = {
        "fid": ["VA", "VB"],
        "filas": np.array([0, 1, 2, 3]),
        "instance_bag": np.array([0, 0, 1, 1]),
        "n_bolsas": 2,
        "n_obs": np.array([2, 2]),
    }
    X = np.arange(4 * 3, dtype=float).reshape(4, 3)

    _tabla, metadata = simular_bolsas(
        predictor, X, seleccion=seleccion, feature_names=["a", "b", "c"],
        overrides=[{"variable": "b", "valor": 99.0}],
    )

    X_sim = metadata["X_simulado"]
    assert X_sim.shape == (4, 3)
    assert list(X_sim[:, 1]) == [99.0] * 4          # la override esta aplicada
    assert list(X_sim[:, 0]) == list(X[:, 0])       # y nada mas se toco
