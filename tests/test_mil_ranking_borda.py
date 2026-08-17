"""Contract tests for the Borda ranking of per-bag variable relevances.

Los dos defectos que estas pruebas fijan estuvieron vivos en la rama
`mode == "full"` del cuaderno 05 y sobrevivieron a una suite en verde, porque el
pegamento vivia dentro de una celda que solo se ejecuta con `mode == "full"`:

  1. el productor de relevancias devuelve una LISTA alineada por posicion con
     los indices que recibio, no un dict indexado por bolsa. La celda le hacia
     `.get(int(i), {})` y reventaba con `AttributeError`.
  2. `agregar_borda` devuelve `group_cols + ["RELEVANCIA_VARS"]` -- no hay
     columna `_var` --, asi que el `.get("_var", pd.Series(dtype=object))` de la
     celda producia una Serie vacia en silencio y la nota de
     exposicion/severidad no se escribia nunca.

Quien PRODUCE esas relevancias cambio: era un extractor Kernel SHAP, retirado
del proyecto entero. La agregacion que se prueba aqui es independiente de su
origen -- recibe dicts `{variable: puntaje}` ordenados de mayor a menor y los
consensua por PUESTOS --, asi que sigue siendo el contrato correcto para el
metodo que reemplazo a SHAP: la relevancia hacia el UITI minimo.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chec_impacto.interpretability.borda import agregar_borda
from chec_impacto.interpretability.mil_vano_ventana import (
    COLUMNAS_EXPOSICION_SEVERIDAD,
    NOTA_EXPOSICION_SEVERIDAD,
    construir_ranking_borda,
    nota_exposicion_severidad,
)


def _keys() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CIRCUITO": ["AGU23L14", "AGU23L14", "AMA23L12", "AMA23L12"],
            "FID_VANO": [10, 10, 20, 21],
            "VENTANA": ["m1", "m2", "m1", "m1"],
        }
    )


def test_agregar_borda_no_expone_columna_var():
    """Fija el defecto 2 en su origen: el marco agregado no lleva `_var`."""
    frame = pd.DataFrame(
        {
            "CIRCUITO": ["A"],
            "FID_VANO": [1],
            "VENTANA": ["m1"],
            "_TOP_VARS": [{"CAPACIDAD_NOMINAL": 0.5}],
        }
    )
    salida = agregar_borda(frame, group_cols=["CIRCUITO", "FID_VANO", "VENTANA"])
    assert "_var" not in salida.columns
    assert "RELEVANCIA_VARS" in salida.columns


def test_la_familia_exposicion_severidad_son_esas_dos_y_no_mas():
    """La composicion exacta, no solo su comportamiento.

    Venia de tests/test_generate_notebook_10.py, donde viajaba de polizon en una
    prueba sobre el TEXTO del cuaderno. Al retirarse SHAP esa prueba perdio su
    objeto, y esta afirmacion -- que no tenia nada que ver con el cuaderno -- se
    habria ido con ella.
    """
    assert {"CAPACIDAD_NOMINAL", "PROMEDIO_KWH_TRF"} == set(COLUMNAS_EXPOSICION_SEVERIDAD)


def test_nota_marca_solo_la_familia_exposicion_severidad():
    for nombre in COLUMNAS_EXPOSICION_SEVERIDAD:
        assert nota_exposicion_severidad(nombre) == NOTA_EXPOSICION_SEVERIDAD
    # CNT_VN queda deliberadamente FUERA de la familia (D6): responde a
    # COD_EQ_PROTEGE, no a exposicion.
    for nombre in ("CNT_VN", "temp_9", "COD_CAUSA_28"):
        assert nota_exposicion_severidad(nombre) == ""


def test_ranking_borda_acepta_la_lista_que_devuelve_el_productor():
    """Fija el defecto 1: top_vars llega como LISTA alineada con los indices."""
    keys = _keys()
    indices = np.array([0, 2, 3])
    top_vars_por_bolsa = [
        {"CAPACIDAD_NOMINAL": 0.9, "temp_9": 0.4},
        {"temp_9": 0.7},
        {"CNT_TRF": 0.6, "CAPACIDAD_NOMINAL": 0.1},
    ]

    ranking = construir_ranking_borda(keys, indices, top_vars_por_bolsa)

    assert not ranking.empty
    assert {"CIRCUITO", "FID_VANO", "VENTANA", "_var", "_borda"} <= set(ranking.columns)
    # una fila por (grupo, variable), no un dict opaco
    assert len(ranking) == 5


def test_ranking_borda_escribe_la_nota_de_exposicion_severidad():
    """Fija el defecto 2: la nota debe LLEGAR a las filas, no quedar vacia."""
    keys = _keys()
    indices = np.array([0, 3])
    top_vars_por_bolsa = [
        {"CAPACIDAD_NOMINAL": 0.9, "temp_9": 0.4},
        {"CNT_TRF": 0.6},
    ]

    ranking = construir_ranking_borda(keys, indices, top_vars_por_bolsa)

    notas = dict(zip(ranking["_var"], ranking["nota_exposicion_severidad"]))
    assert notas["CAPACIDAD_NOMINAL"] == NOTA_EXPOSICION_SEVERIDAD
    assert notas["temp_9"] == ""
    assert notas["CNT_TRF"] == ""
    # y al menos una fila anotada de verdad -- la version rota daba todo NaN
    assert (ranking["nota_exposicion_severidad"] != "").sum() == 1


def test_ranking_borda_ordena_por_puntaje_dentro_del_grupo():
    keys = _keys()
    indices = np.array([0])
    # dict ordenado por relevancia descendente, como lo entrega el productor
    top_vars_por_bolsa = [{"CAPACIDAD_NOMINAL": 0.9, "temp_9": 0.4, "CNT_TRF": 0.1}]

    ranking = construir_ranking_borda(keys, indices, top_vars_por_bolsa)

    assert list(ranking["_var"]) == ["CAPACIDAD_NOMINAL", "temp_9", "CNT_TRF"]
    assert ranking["_borda"].is_monotonic_decreasing


def test_ranking_borda_rechaza_longitudes_desalineadas():
    """La guarda que habria matado el bug del dict/lista en el acto."""
    keys = _keys()
    with pytest.raises(ValueError, match="alineada"):
        construir_ranking_borda(keys, np.array([0, 1, 2]), [{"temp_9": 0.5}])


def test_ranking_borda_tolera_bolsas_sin_top_vars():
    keys = _keys()
    ranking = construir_ranking_borda(keys, np.array([0, 1]), [{}, {"temp_9": 0.5}])
    assert list(ranking["_var"]) == ["temp_9"]


def test_ranking_borda_sin_ninguna_relevancia_devuelve_frame_vacio_tipado():
    keys = _keys()
    ranking = construir_ranking_borda(keys, np.array([0, 1]), [{}, {}])
    assert ranking.empty
    assert {"_var", "_borda", "nota_exposicion_severidad"} <= set(ranking.columns)
