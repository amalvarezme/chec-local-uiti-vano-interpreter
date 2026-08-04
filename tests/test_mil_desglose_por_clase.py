"""RED/GREEN tests for the per-class breakdown (confusion matrix + per-class F1).

macro-F1 alone cannot distinguish "the model is uniformly mediocre" from
"the model abandoned one class". On this dataset the distinction is the
whole question: `Alto` is 10.21% of the within-vano-variation subset (6,342
of 62,114 bags) and is the class CHEC actually cares about. A model that
predicts the other three perfectly and never predicts `Alto` scores 89.8%
accuracy and 0.75 macro-F1 -- and the observed model scores 0.7704, close
enough to 3/4 that the question cannot be waved away.

`accuracy` is reported alongside but never as the headline: the majority
baseline already scores 0.4384 accuracy against 0.1524 macro-F1.
"""

from __future__ import annotations

import numpy as np
import pytest

from chec_impacto.interpretability.mil_vano_ventana import desglose_por_clase


def _obs() -> np.ndarray:
    # 10 bags: 4 of class 0, 3 of class 1, 2 of class 2, 1 of class 3
    return np.array([0, 0, 0, 0, 1, 1, 1, 2, 2, 3])


def test_perfect_predictions_score_one_everywhere():
    obs = _obs()
    d = desglose_por_clase(obs, {"modelo": obs.copy()}, np.ones(len(obs), bool))["modelo"]

    assert d["accuracy"] == pytest.approx(1.0)
    assert d["macro_f1"] == pytest.approx(1.0)
    assert np.array_equal(d["matriz_confusion"], np.diag([4, 3, 2, 1]))
    for fila in d["por_clase"]:
        assert fila["f1"] == pytest.approx(1.0)


def test_abandoning_the_rare_class_is_visible_in_the_breakdown_but_not_in_accuracy():
    """The exact failure mode macro-F1 hides and accuracy rewards."""
    obs = _obs()
    # perfecto en 0/1/2, nunca predice la clase 3 (la manda a la 2)
    pred = obs.copy()
    pred[obs == 3] = 2

    d = desglose_por_clase(obs, {"modelo": pred}, np.ones(len(obs), bool))["modelo"]
    por_clase = {f["clase"]: f for f in d["por_clase"]}

    assert d["accuracy"] == pytest.approx(0.9)  # alta, y enganosa
    assert por_clase[3]["f1"] == pytest.approx(0.0)
    assert por_clase[3]["recall"] == pytest.approx(0.0)
    assert por_clase[3]["soporte"] == 1
    assert d["clases_abandonadas"] == [3]


def test_no_class_is_flagged_as_abandoned_when_all_are_predicted():
    obs = _obs()
    d = desglose_por_clase(obs, {"modelo": obs.copy()}, np.ones(len(obs), bool))["modelo"]
    assert d["clases_abandonadas"] == []


def test_confusion_matrix_rows_are_observed_and_columns_predicted():
    """Orientation is not a detail: reading it transposed inverts the diagnosis."""
    obs = np.array([0, 0, 1, 1])
    pred = np.array([0, 1, 1, 1])  # una bolsa observada 0 predicha como 1
    m = desglose_por_clase(obs, {"m": pred}, np.ones(4, bool))["m"]["matriz_confusion"]
    assert m[0, 1] == 1, "fila = clase OBSERVADA, columna = clase PREDICHA"
    assert m[1, 0] == 0


def test_matrix_always_covers_the_four_criticality_tiers():
    """Even if an arm never predicts a tier, the matrix keeps its 4x4 shape."""
    obs = np.array([0, 0, 1, 1])
    d = desglose_por_clase(obs, {"m": np.zeros(4, int)}, np.ones(4, bool))["m"]
    assert d["matriz_confusion"].shape == (4, 4)
    assert [f["clase"] for f in d["por_clase"]] == [0, 1, 2, 3]


def test_mask_restricts_the_evaluation_to_the_declared_subset():
    obs = np.array([0, 0, 3, 3])
    pred = np.array([0, 0, 0, 0])
    mask = np.array([True, True, False, False])
    d = desglose_por_clase(obs, {"m": pred[mask]}, mask)["m"]
    assert d["n"] == 2
    assert d["accuracy"] == pytest.approx(1.0)


def test_macro_f1_matches_sklearn_so_it_can_be_cross_checked():
    from sklearn.metrics import f1_score

    rng = np.random.default_rng(0)
    obs = rng.integers(0, 4, 200)
    pred = rng.integers(0, 4, 200)
    d = desglose_por_clase(obs, {"m": pred}, np.ones(200, bool))["m"]
    assert d["macro_f1"] == pytest.approx(f1_score(obs, pred, average="macro"))


def test_every_arm_is_broken_down_independently():
    obs = _obs()
    salida = desglose_por_clase(
        obs,
        {"modelo": obs.copy(), "mayoritaria": np.zeros(len(obs), int)},
        np.ones(len(obs), bool),
    )
    assert set(salida) == {"modelo", "mayoritaria"}
    assert salida["modelo"]["macro_f1"] > salida["mayoritaria"]["macro_f1"]
    assert salida["mayoritaria"]["clases_abandonadas"] == [1, 2, 3]


def test_prediction_length_must_match_the_mask():
    obs = _obs()
    with pytest.raises(ValueError, match="mask|longitud"):
        desglose_por_clase(obs, {"m": np.zeros(3, int)}, np.ones(len(obs), bool))
