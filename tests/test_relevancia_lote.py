"""RED/GREEN tests for the batch relevance sweep behind notebook 07.

Notebook 06 answers the question for the handful of vanos on screen. This answers
it for the WHOLE dataset in one go, which is what a planning spreadsheet needs:
one row per (vano, ventana) with its group and the ten variables that matter most
for it.

Two things make the batch version its own module rather than a loop over 06's
function. The first is arithmetic: every forward pass already returns one u-hat
per bag, so sweeping all 111.233 bags costs the SAME 197 passes as sweeping five
-- measured, one minute for the entire dataset. A loop per selection would take
days for nothing.

The second is that the question flips depending on where the bag already is. For
a bag in Alto, Medio-Alto or Medio the useful ranking is what would take it DOWN
to the lowest group. For a bag already in the lowest group there is nowhere to go
down, and the ranking that carries information is the opposite one: what would
take it OUT -- the variables its permanence is most fragile to. Ranking a bag in
the lowest group by achievable drop returns ten variables that move nothing,
which is exactly the failure already measured in 06's panel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chec_impacto.models.criticality_assignment import Geometria
from chec_local_interpreter.relevancia_lote import (
    SIN_EVENTOS,
    barrer_todas_las_bolsas,
    gates_medias_por_grupo,
    guardar_hojas,
    ranking_por_bolsa,
    relevancia_media_por_grupo,
    subconjunto_de_bolsas,
    tabla_vano_ventana,
)
from chec_local_interpreter.vano_controls import Knob


def _knob(knob_id, bounds=(0.0, 10.0), feature_names=None, kind="numeric",
          categories=None):
    return Knob(id=knob_id, label=knob_id, kind=kind,
                feature_names=tuple(feature_names or (knob_id,)),
                bounds=bounds, categories=categories, default=None, step=None)


def _geometria():
    """Centroides ordenados por el eje de u: `log10(u) = -1, 0, 1, 2`."""
    return Geometria(
        logs=(False, True), offset=np.array([0.0, 0.0]), scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, -1.0], [0.0, 0.0], [0.0, 1.0], [0.0, 2.0]]),
    )


class _Predictor:
    def __init__(self, funciones):
        self.geometria = _geometria()
        self.funciones = funciones

    def predict(self, X_inst, instance_bag=None):
        X = np.asarray(X_inst, dtype=float)
        ib = np.asarray(instance_bag)
        n = int(ib.max()) + 1 if ib.size else 0
        return np.array([self.funciones[b](X[ib == b].mean(axis=0)) for b in range(n)])


FEATURES = ["x", "y"]
IB = np.array([0, 1])
N_OBS = np.array([1.0, 1.0])


def _barrido(funciones, knobs, X=None, puntos=3):
    return barrer_todas_las_bolsas(
        _Predictor(funciones), np.zeros((2, 2)) if X is None else X,
        instance_bag=IB, feature_names=FEATURES, knobs=knobs, puntos=puntos)


# --- el barrido ------------------------------------------------------------------------


def test_the_sweep_keeps_both_the_lowest_and_the_highest_reachable_u():
    """Los dos extremos alcanzables, y no solo el minimo: el minimo contesta que
    baja al vano, y el maximo contesta de que depende que se quede donde esta.
    Cual de los dos se usa lo decide el grupo de cada bolsa, no el barrido."""
    barrido = _barrido([lambda v: 1.0 + v[0], lambda v: 1.0 + v[0]],
                       [_knob("A", feature_names=("x",))])

    assert barrido.u_min[0, 0] == pytest.approx(1.0)     # x = 0
    assert barrido.u_max[0, 0] == pytest.approx(11.0)    # x = 10
    assert barrido.valor(0, 0, "min") == pytest.approx(0.0)
    assert barrido.valor(0, 0, "max") == pytest.approx(10.0)


def test_categorical_knobs_are_swept_through_their_categories():
    """Su rejilla son sus categorias. Sin ellos, el conductor, el calibre del
    neutro y el tipo de proteccion -- tres obras que CHEC ejecuta -- quedan fuera
    de todo el analisis."""
    barrido = _barrido(
        [lambda v: 1.0 + v[1], lambda v: 1.0],
        [_knob("CAT", kind="categorical", bounds=None, categories=("a", "b"),
               feature_names=("y",))])

    assert barrido.labels == ["CAT"]
    assert barrido.candidatos[0] == ["a", "b"]


def test_a_constant_knob_is_left_out():
    """Un unico valor observado no mueve nada, y probarlo gasta una pasada sobre
    288 mil instancias."""
    barrido = _barrido([lambda v: 1.0, lambda v: 1.0],
                       [_knob("K", feature_names=("x",)),
                        _knob("C", kind="constant", bounds=None, feature_names=("y",))])

    assert barrido.labels == ["K"]


# --- el ranking, que cambia de pregunta segun el grupo ----------------------------------


def test_a_bag_above_the_lowest_group_is_ranked_by_what_takes_it_down():
    barrido = _barrido([lambda v: 100.0 - 9.9 * v[0], lambda v: 100.0],
                       [_knob("BAJA", feature_names=("x",)),
                        _knob("QUIETA", feature_names=("y",))])

    rank = ranking_por_bolsa(barrido, n_obs=N_OBS, geometria=_geometria(), top=2)

    assert rank["direccion"][0] == "bajar"
    assert rank["labels"][0][0] == "BAJA"


def test_a_bag_already_in_the_lowest_group_is_ranked_by_what_takes_it_out():
    """No hay adonde bajar. Ordenarla por caida alcanzable devuelve diez variables
    que no mueven nada -- el mismo defecto que ya se midio en el panel de 06 --,
    asi que la pregunta se invierte: que la sacaria de ahi."""
    barrido = _barrido([lambda v: 0.01 + 9.9 * v[0], lambda v: 0.01],
                       [_knob("SUBE", feature_names=("x",)),
                        _knob("QUIETA", feature_names=("y",))])

    rank = ranking_por_bolsa(barrido, n_obs=N_OBS, geometria=_geometria(), top=2)

    assert rank["direccion"][0] == "sostener"
    assert rank["labels"][0][0] == "SUBE"


def test_the_top_reserves_room_for_both_groups_of_variables():
    """Un ranking copado por el clima no deja ni una palanca que una cuadrilla
    pueda ejecutar. Mismo criterio que el panel de 06."""
    knobs = [_knob(f"E{i}", feature_names=("x",)) for i in range(3)]
    knobs += [_knob(f"I{i}", feature_names=("y",)) for i in range(3)]
    grupos = {f"E{i}": "Escenario" for i in range(3)}
    grupos.update({f"I{i}": "Intervencion" for i in range(3)})
    # Las de escenario bajan mucho mas que las de intervencion.
    barrido = _barrido([lambda v: 100.0 - 9.0 * v[0] - 0.1 * v[1], lambda v: 100.0],
                       knobs)

    rank = ranking_por_bolsa(barrido, n_obs=N_OBS, geometria=_geometria(), top=4,
                             grupos=grupos)

    presentes = {grupos[k] for k in rank["knob_ids"][0]}
    assert presentes == {"Escenario", "Intervencion"}


# --- la tabla que se exporta -------------------------------------------------------------


def test_a_vano_window_without_events_is_labelled_and_left_without_ranking():
    """Sin celda no hay bolsa, sin bolsa no hay prediccion y sin prediccion no hay
    ranking. La etiqueta lo dice; inventarle un grupo seria afirmar algo que nadie
    midio, y el grupo mas bajo NO es la ausencia de datos."""
    claves = pd.DataFrame({"CIRCUITO": ["C1"], "FID_VANO": ["V1"], "VENTANA": ["V1"]})
    tabla = tabla_vano_ventana(
        claves=claves, ventanas=["V1", "V2"], clases=np.array([2]),
        nombres_clase=["Bajo", "Medio", "Medio-Alto", "Alto"],
        ranking={"labels": [["A", "B"]], "direccion": ["bajar"]}, top=2,
    )

    sin = tabla[tabla["VENTANA"] == "V2"].iloc[0]
    assert sin["GRUPO"] == SIN_EVENTOS
    assert sin["TOP_1"] == ""
    assert sin["FID_VANO"] == "V1" and sin["CIRCUITO"] == "C1"


def test_every_vano_gets_a_row_for_every_window():
    """La rejilla es completa a proposito: un vano al que le faltan ventanas se lee
    como que no existio en ellas, cuando lo que paso es que no tuvo eventos."""
    claves = pd.DataFrame({"CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V2"],
                           "VENTANA": ["V1", "V2"]})
    tabla = tabla_vano_ventana(
        claves=claves, ventanas=["V1", "V2", "V3"], clases=np.array([0, 3]),
        nombres_clase=["Bajo", "Medio", "Medio-Alto", "Alto"],
        ranking={"labels": [["A"], ["B"]], "direccion": ["sostener", "bajar"]}, top=1,
    )

    assert len(tabla) == 2 * 3
    assert set(tabla["VENTANA"]) == {"V1", "V2", "V3"}
    assert tabla.loc[(tabla.FID_VANO == "V1") & (tabla.VENTANA == "V1"),
                     "GRUPO"].iloc[0] == "Bajo"


def test_the_direction_column_says_which_question_the_top_answers():
    """Las dos columnas de top no significan lo mismo, y sin decirlo la hoja se
    lee como si el ranking de un vano en Bajo fuera "como bajarlo mas"."""
    claves = pd.DataFrame({"CIRCUITO": ["C1"], "FID_VANO": ["V1"], "VENTANA": ["V1"]})
    tabla = tabla_vano_ventana(
        claves=claves, ventanas=["V1"], clases=np.array([0]),
        nombres_clase=["Bajo", "Medio", "Medio-Alto", "Alto"],
        ranking={"labels": [["A"]], "direccion": ["sostener"]}, top=1,
    )

    assert "sosten" in tabla["LECTURA_DEL_TOP"].iloc[0].lower()


# --- las barras por grupo ----------------------------------------------------------------


def test_the_group_bars_average_the_reachable_drop_over_the_bags_of_each_group():
    """La pregunta del cuaderno 07 no es que mueve a UN vano sino que mueve al
    GRUPO: con 111 mil bolsas, el promedio por grupo es lo unico que se puede
    leer de un vistazo."""
    barrido = _barrido([lambda v: 100.0 - 9.9 * v[0], lambda v: 100.0 - 9.9 * v[0]],
                       [_knob("A", feature_names=("x",))])

    resumen = relevancia_media_por_grupo(
        barrido, clases=np.array([2, 3]), n_clases=4)

    assert set(resumen) <= {0, 1, 2, 3}
    assert resumen[2]["A"]["media"] > 0
    assert 1 not in resumen or not resumen[1]


def test_the_summary_carries_the_spread_across_the_bags_of_the_group():
    """Una media alta con una desviacion del mismo tamano dice que la variable
    funciona en unos vanos del grupo y no en otros, y esa es una recomendacion
    distinta -- revisar vano por vano -- de la que da una media alta y estable.
    Sin la barra de error las dos se dibujan identicas."""
    # Dos bolsas del MISMO grupo que reaccionan de forma muy distinta.
    barrido = _barrido([lambda v: 100.0 - 9.9 * v[0], lambda v: 100.0],
                       [_knob("A", feature_names=("x",))])

    resumen = relevancia_media_por_grupo(barrido, clases=np.array([2, 2]), n_clases=4)

    assert resumen[2]["A"]["desviacion"] > 0
    assert resumen[2]["A"]["n_bolsas"] == 2


def test_a_group_whose_bags_all_react_alike_has_no_spread():
    barrido = _barrido([lambda v: 100.0 - 9.9 * v[0], lambda v: 100.0 - 9.9 * v[0]],
                       [_knob("A", feature_names=("x",))])

    resumen = relevancia_media_por_grupo(barrido, clases=np.array([2, 2]), n_clases=4)

    assert resumen[2]["A"]["desviacion"] == pytest.approx(0.0)


def test_the_gates_are_split_by_group_and_not_averaged_yet():
    """Quien decide si el grafo se puede reconstruir es
    `grafo_por_grupo_si_no_colapsado`, y esa decision depende de si las compuertas
    VARIAN dentro del grupo. Promediarlas aqui tiraria justo esa informacion."""
    gates = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    por_grupo = gates_medias_por_grupo(gates, np.array([2, 2, 3]))

    assert por_grupo[2].shape == (2, 2)
    assert por_grupo[3].shape == (1, 2)
    assert 0 not in por_grupo


# --- el guardado --------------------------------------------------------------------------


def test_saving_keeps_every_column(tmp_path):
    """`DataFrame.to_excel` recorre por COLUMNAS y `constant_memory` descarta una fila
    en cuanto el cursor avanza: juntos producen un archivo que se abre sin error y
    trae solo la primera columna. Se detecto escribiendo las 301 mil filas de 07 y
    leyendolas de vuelta -- 1,5 MB y una sola celda con grupo -- y esta prueba es lo
    que impide que vuelva a pasar en silencio."""
    tabla = pd.DataFrame({"A": [f"a{i}" for i in range(50)],
                          "B": ["x"] * 50,
                          "C": list(range(50))})
    destino = tmp_path / "hoja.xlsx"

    guardar_hojas({"datos": tabla}, destino)

    leida = pd.read_excel(destino, sheet_name="datos")
    assert list(leida.columns) == ["A", "B", "C"]
    assert leida["B"].notna().all(), "la segunda columna se perdio al escribir"
    assert leida["C"].tolist() == list(range(50))


def test_saving_writes_every_sheet(tmp_path):
    destino = tmp_path / "hoja.xlsx"

    guardar_hojas({"uno": pd.DataFrame({"A": [1]}), "dos": pd.DataFrame({"B": [2]})},
                  destino)

    assert set(pd.ExcelFile(destino).sheet_names) == {"uno", "dos"}


def test_an_empty_cell_stays_empty_and_does_not_become_nan_text(tmp_path):
    """Las celdas sin eventos llevan el top vacio. Escritas como el texto "nan"
    convertirian una ausencia en un valor."""
    destino = tmp_path / "hoja.xlsx"

    guardar_hojas({"d": pd.DataFrame({"A": ["x", None], "B": ["", "y"]})}, destino)

    leida = pd.read_excel(destino, sheet_name="d")
    assert pd.isna(leida["A"].iloc[1])


# --- el subconjunto que alimenta al selector del tablero --------------------------------


class _BagIndex:
    def __init__(self, claves, counts):
        self.keys = claves
        self.counts = np.asarray(counts, dtype=np.int64)
        self.offsets = np.concatenate([[0], np.cumsum(self.counts)])


def _indice():
    claves = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C2"],
        "FID_VANO": ["V1", "V2", "V3"],
        "VENTANA": ["W1", "W2", "W1"],
    })
    return _BagIndex(claves, [2, 1, 3])


def test_without_filters_the_subset_is_the_whole_dataset():
    """El 07 arranca sobre todo y se recorta solo si el usuario lo pide."""
    sub = subconjunto_de_bolsas(_indice())

    assert sub["n_bolsas"] == 3
    assert sub["filas"].tolist() == [0, 1, 2, 3, 4, 5]


def test_the_subset_can_be_cut_by_circuit_by_window_or_by_both():
    indice = _indice()

    assert subconjunto_de_bolsas(indice, circuito="C1")["n_bolsas"] == 2
    assert subconjunto_de_bolsas(indice, ventana="W1")["n_bolsas"] == 2
    assert subconjunto_de_bolsas(indice, circuito="C1", ventana="W1")["n_bolsas"] == 1


def test_the_instance_bag_is_renumbered_from_zero():
    """El modelo toma `n_bags` como `instance_bag.max() + 1`: conservar los ids
    originales reservaria una bolsa vacia por cada celda que quedo fuera y
    desplazaria todos los resultados."""
    sub = subconjunto_de_bolsas(_indice(), circuito="C2")

    assert sub["instance_bag"].tolist() == [0, 0, 0]
    assert sub["filas"].tolist() == [3, 4, 5]
    assert sub["n_obs"].tolist() == [3.0]


def test_an_empty_subset_reports_zero_without_inventing_rows():
    sub = subconjunto_de_bolsas(_indice(), circuito="NO_EXISTE")

    assert sub["n_bolsas"] == 0
    assert sub["filas"].size == 0
