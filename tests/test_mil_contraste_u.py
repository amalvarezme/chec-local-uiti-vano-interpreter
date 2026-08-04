"""RED/GREEN tests for the u-space contrast against the RandomForest baseline.

Both arms predict the SAME quantity -- `u` (accumulated UITI) -- and both
pass through the SAME frozen nearest-centroid rule to become a class. So a
macro-F1 gap has exactly two possible homes: the regression of `u`, or the
class mapping on top of it. Comparing only classes cannot tell them apart,
and every measurement so far has compared only classes.

`predecir_u_estructural` exists so the baseline's `û` is observable at all:
`baseline_estructural` returned the class and threw the `û` away, which made
the contrast impossible without refitting.
"""

from __future__ import annotations

import numpy as np
import pytest

from chec_impacto.interpretability.mil_vano_ventana import (
    baseline_estructural,
    contraste_u,
    predecir_u_estructural,
)
from chec_impacto.models.criticality_assignment import Geometria, asignar_clase


def _geometria() -> Geometria:
    return Geometria(
        logs=(False, True),
        offset=np.array([1.0, -3.0]),
        scale=np.array([45.0, 7.424386]),
        centroides=np.array([[0.0, 0.55], [0.02, 0.65], [0.04, 0.75], [0.06, 0.88]]),
    )


def _datos(n: int = 120, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 5))
    u = np.expm1(2.0 + X[:, 0] * 1.5 + rng.normal(scale=0.3, size=n))
    return X, np.abs(u) + 1.0


# ---------------------------------------------------------------------------
# The baseline's û must be observable, and identical to what it classifies.
# ---------------------------------------------------------------------------


def test_structural_u_is_exactly_what_the_baseline_classifies():
    """Extracting û must not change the baseline's published class output."""
    X, y = _datos()
    geo = _geometria()
    n_obs = np.full(len(y), 2.0)
    X_tr, y_tr, X_te, n_te = X[:80], y[:80], X[80:], n_obs[80:]

    u_hat = predecir_u_estructural(X_tr, y_tr, X_te, seed=42)
    clase_desde_u, _ = asignar_clase(n_te, u_hat, geo)
    clase_publicada = baseline_estructural(X_tr, y_tr, X_te, n_te, geo, seed=42)

    assert np.array_equal(clase_desde_u, clase_publicada)


def test_structural_u_is_deterministic_for_a_fixed_seed():
    X, y = _datos()
    a = predecir_u_estructural(X[:80], y[:80], X[80:], seed=42)
    b = predecir_u_estructural(X[:80], y[:80], X[80:], seed=42)
    assert np.array_equal(a, b)


def test_structural_u_is_strictly_positive():
    """It feeds log10 downstream; a non-positive û would hit the clamp."""
    X, y = _datos()
    assert np.all(predecir_u_estructural(X[:80], y[:80], X[80:], seed=42) > 0)


# ---------------------------------------------------------------------------
# The contrast itself.
# ---------------------------------------------------------------------------


def test_contrast_ranks_a_perfect_predictor_above_a_constant_one():
    y = np.array([1.0, 10.0, 100.0, 1000.0, 5.0, 50.0])
    mask = np.ones(len(y), bool)
    tabla = contraste_u(y, {"perfecto": y.copy(), "constante": np.full(len(y), 42.0)}, mask)

    fila = {r["arm"]: r for r in tabla.to_dict("records")}
    assert fila["perfecto"]["spearman"] == pytest.approx(1.0)
    assert fila["perfecto"]["mae_log1p"] == pytest.approx(0.0, abs=1e-9)
    assert fila["constante"]["mae_log1p"] > fila["perfecto"]["mae_log1p"]


def test_contrast_measures_in_log1p_space_where_the_target_lives():
    """The model regresses log1p(u); MAE on raw u would be dominated by the tail."""
    y = np.array([1.0, 1e5])
    mask = np.ones(2, bool)
    # error de un factor 10 en el valor grande
    tabla = contraste_u(y, {"a": np.array([1.0, 1e4])}, mask)
    mae = tabla.loc[tabla["arm"] == "a", "mae_log1p"].iloc[0]
    assert mae == pytest.approx(np.log(10.0) / 2, rel=1e-3)


def test_contrast_reports_spearman_which_ignores_monotone_rescaling():
    """Separates 'ranks the bags right' from 'gets the level right'."""
    y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    tabla = contraste_u(y, {"escalado": y * 7.0}, np.ones(5, bool))
    fila = tabla.iloc[0]
    assert fila["spearman"] == pytest.approx(1.0)
    assert fila["mae_log1p"] > 0.0


def test_contrast_honours_the_mask():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    mask = np.array([True, True, False, False])
    tabla = contraste_u(y, {"a": np.array([1.0, 2.0])}, mask)
    assert int(tabla.iloc[0]["n"]) == 2


def test_contrast_rejects_a_length_mismatch():
    with pytest.raises(ValueError, match="mask|longitud"):
        contraste_u(np.arange(4.0) + 1, {"a": np.ones(3)}, np.ones(4, bool))


def test_contrast_tolerates_a_non_positive_prediction_without_nan():
    y = np.array([1.0, 2.0, 3.0])
    tabla = contraste_u(y, {"a": np.array([-5.0, 0.0, 3.0])}, np.ones(3, bool))
    assert np.isfinite(tabla.iloc[0]["mae_log1p"])
