"""RED/GREEN tests for the viewer helpers of notebook 10.

The notebook now runs by default WITHOUT training: it reads the saved
artifact and the saved out-of-fold predictions and renders them. These are
the two pieces that turn stored arrays into something readable, and they
live in the library rather than in a cell because a cell-only helper is
exactly what shipped the broken exposure/severity annotation.
"""

from __future__ import annotations

import numpy as np
import pytest

from chec_impacto.interpretability.mil_vano_ventana import (
    matriz_confusion_porcentaje,
    tabla_variables,
)


def test_percentages_are_normalised_per_observed_row():
    """Row-normalised: each row answers 'of the bags that WERE k, where did
    they go?' -- the recall view, which is the one that shows an abandoned
    class."""
    m = np.array([[8, 2, 0, 0], [1, 7, 2, 0], [0, 0, 5, 5], [0, 0, 0, 10]])
    pct = matriz_confusion_porcentaje(m)
    assert np.allclose(pct.sum(axis=1), 100.0)
    assert pct[0, 0] == pytest.approx(80.0)
    assert pct[2, 3] == pytest.approx(50.0)


def test_empty_observed_row_becomes_zeros_not_nan():
    """A tier with no observed bags must not poison the table with NaN."""
    m = np.array([[5, 5], [0, 0]])
    pct = matriz_confusion_porcentaje(m)
    assert np.all(np.isfinite(pct))
    assert np.all(pct[1] == 0.0)


def test_variable_table_lists_every_feature_once_with_its_modality():
    features = ["a", "b", "c", "d"]
    modalidades = {"climaticos": [0, 1], "estructurales": [2, 3]}
    A = np.zeros((4, 4))
    A[0, 1] = 0.5  # a -> b
    A[1, 2] = 0.8  # b -> c  (cruza modalidad)

    t = tabla_variables(features, modalidades, A)
    assert list(t["variable"]) == features
    assert list(t["modalidad"]) == ["climaticos", "climaticos", "estructurales", "estructurales"]


def test_variable_table_reports_graph_degree_and_isolation():
    features = ["a", "b", "c", "ind"]
    modalidades = {"m": [0, 1, 2, 3]}
    A = np.zeros((4, 4))
    A[0, 1] = 0.5
    A[1, 2] = 0.8

    t = tabla_variables(features, modalidades, A).set_index("variable")
    assert t.loc["a", "grado_salida"] == 1
    assert t.loc["a", "grado_entrada"] == 0
    assert t.loc["b", "grado_entrada"] == 1 and t.loc["b", "grado_salida"] == 1
    # `ind` no toca el grafo: la propagacion nunca modifica su columna
    assert t.loc["ind", "en_grafo"] is np.False_ or not t.loc["ind", "en_grafo"]
    assert t.loc["a", "en_grafo"]


def test_variable_table_flags_cross_modality_edges():
    """The model's only graph-borne cross-modality path -- 10 of 64 edges on
    the real data -- should be visible per variable, not just as a total."""
    features = ["a", "b", "c"]
    modalidades = {"clima": [0], "estruct": [1, 2]}
    A = np.zeros((3, 3))
    A[0, 1] = 1.0  # clima -> estruct: cruza
    A[1, 2] = 1.0  # estruct -> estruct: no cruza

    t = tabla_variables(features, modalidades, A).set_index("variable")
    assert t.loc["a", "aristas_cruzadas"] == 1
    assert t.loc["b", "aristas_cruzadas"] == 1
    assert t.loc["c", "aristas_cruzadas"] == 0


def test_variable_table_rejects_a_width_mismatch():
    with pytest.raises(ValueError, match="adyacencia|features"):
        tabla_variables(["a", "b"], {"m": [0, 1]}, np.zeros((3, 3)))
