"""RED/GREEN tests for D6 (criticality assignment from 01.4's KMeans geometry).

Covers:
  - `scripts.extract_geometrias_014.extraer_geometrias_014` -- read-only
    extraction of 01.4's cell-7 `display_data` payload.
  - `chec_impacto.models.criticality_assignment` -- `Geometria`,
    `cargar_geometria_014`, `asignar_clase`, `distribucion_suave`.

See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain
    `criticality-assignment-from-014`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D6)

`tests/fixtures/notebook_01_4_fixture.ipynb` is a small, committed notebook
shaped like 01.4: its cell 7 embeds the REAL `espacios`/`grupos`/`geometrias`
JSON read from the committed 01.4 notebook on 2026-08-02, wrapped in
synthetic surrounding markup so the marker-based parser is exercised against
realistic noise, not an isolated JSON blob. The expected numbers below for
space `"2"` are copied from that same real extraction (log_x=False,
log_y=True, prep='minmax' -- the hardcoded canonical space).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from chec_impacto.models.criticality_assignment import (
    CLAVE_ESPACIO_CANONICO,
    EPS_UITI,
    Geometria,
    asignar_clase,
    cargar_geometria_014,
    distribucion_suave,
)
from scripts.extract_geometrias_014 import extraer_geometrias_014

FIXTURE_NOTEBOOK = Path(__file__).parent / "fixtures" / "notebook_01_4_fixture.ipynb"

# Real values for the canonical space (log_x=False, log_y=True, prep="minmax"), copied
# from 01.4's committed cell-7 output, 2026-08-02 -- NOT fabricated. They are UNCHANGED
# since: on 2026-08-09 the space stopped being a control and its key moved from "2" to
# "0", but the fit -- same data, same seed, same space -- produced the same numbers.
GEOMETRIA_CANONICA_ESPERADA = {
    "logs": (False, True),
    "offset": [1.0, -3.0],
    "scale": [45.0, 7.424386],
    "centroides": [
        [0.012823, 0.406913],
        [0.0257, 0.572701],
        [0.024373, 0.733929],
        [0.237456, 0.7776],
    ],
}

# Raw (n_obs, u) pairs that invert EXACTLY onto each of the four centroids
# above (verified independently by direct computation before writing this
# test), so the expected class for each is unambiguous.
_PUNTOS_EN_CENTROIDE = [
    (1.577035, 1.0497337983054202, 0),
    (2.1565, 17.862954277049855, 1),
    (2.096785, 281.1720793193615, 2),
    (11.68552, 593.2019276116357, 3),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _geometria_prueba() -> Geometria:
    return Geometria(
        logs=GEOMETRIA_CANONICA_ESPERADA["logs"],
        offset=np.array(GEOMETRIA_CANONICA_ESPERADA["offset"]),
        scale=np.array(GEOMETRIA_CANONICA_ESPERADA["scale"]),
        centroides=np.array(GEOMETRIA_CANONICA_ESPERADA["centroides"]),
    )


# --- 2.1/2.2/2.3: extraction + loader -------------------------------------


def test_cargar_geometria_014_desde_extraccion(tmp_path):
    salida = tmp_path / "geometrias_014.json"
    ruta_escrita = extraer_geometrias_014(FIXTURE_NOTEBOOK, salida)
    assert ruta_escrita == salida

    geometria = cargar_geometria_014(salida, clave=CLAVE_ESPACIO_CANONICO)

    assert geometria.logs == GEOMETRIA_CANONICA_ESPERADA["logs"]
    np.testing.assert_allclose(geometria.offset, GEOMETRIA_CANONICA_ESPERADA["offset"])
    np.testing.assert_allclose(geometria.scale, GEOMETRIA_CANONICA_ESPERADA["scale"])
    np.testing.assert_allclose(geometria.centroides, GEOMETRIA_CANONICA_ESPERADA["centroides"])
    assert geometria.centroides.shape == (4, 2)


def test_extraccion_es_de_solo_lectura_sobre_el_notebook_fuente(tmp_path):
    sha_antes = _sha256(FIXTURE_NOTEBOOK)
    extraer_geometrias_014(FIXTURE_NOTEBOOK, tmp_path / "salida.json")
    assert _sha256(FIXTURE_NOTEBOOK) == sha_antes


def test_extraccion_conserva_la_geometria_canonica_y_los_grupos(tmp_path):
    """01.4 used to export eight spaces because its panel let you pick one.

    That control is gone: the space is fixed to (linear x, log10 y, minmax) and exactly one
    geometry is exported. Pinning "the only key is the canonical one" is what keeps a future
    re-enumeration from silently filing the canonical geometry somewhere else -- which is the
    failure this whole sha1 apparatus exists to catch.
    """
    salida = tmp_path / "geometrias_014.json"
    extraer_geometrias_014(FIXTURE_NOTEBOOK, salida)
    import json

    payload = json.loads(salida.read_text(encoding="utf-8"))
    assert payload["grupos"] == ["Bajo", "Medio", "Medio-Alto", "Alto"]
    assert set(payload["geometrias"].keys()) == {CLAVE_ESPACIO_CANONICO}


def test_cargar_geometria_014_clave_ausente_lanza(tmp_path):
    salida = tmp_path / "geometrias_014.json"
    extraer_geometrias_014(FIXTURE_NOTEBOOK, salida)
    with pytest.raises(KeyError):
        cargar_geometria_014(salida, clave="99")


# --- 2.4/2.5: asignar_clase -------------------------------------------------


@pytest.mark.parametrize("n_obs, u, clase_esperada", _PUNTOS_EN_CENTROIDE)
def test_asignar_clase_nearest_centroid_vs_fixture(n_obs, u, clase_esperada):
    geometria = _geometria_prueba()
    clase, n_clamped = asignar_clase(np.array([n_obs]), np.array([u]), geometria)
    assert clase[0] == clase_esperada
    assert n_clamped == 0


def test_asignar_clase_predicho_cero_se_clampa_sin_excepcion():
    geometria = _geometria_prueba()
    clase, n_clamped = asignar_clase(
        np.array([5.0]), np.array([0.0]), geometria, eps=EPS_UITI
    )
    assert n_clamped == 1
    assert np.all(np.isfinite(clase))
    assert clase[0] in (0, 1, 2, 3)


def test_asignar_clase_observado_nunca_clampa():
    """0 of 111,233 measured bags have `uiti_acumulado == 0` (obs #524) --
    the observed path must never hit the clamp branch."""
    geometria = _geometria_prueba()
    u_observado = np.array([0.001, 0.5, 17.9, 281.2, 593.2])
    n_observado = np.full(u_observado.shape, 10.0)
    _, n_clamped = asignar_clase(n_observado, u_observado, geometria)
    assert n_clamped == 0


def test_asignar_clase_forma_invalida_lanza():
    geometria = _geometria_prueba()
    with pytest.raises(ValueError):
        asignar_clase(np.array([1.0, 2.0]), np.array([1.0]), geometria)


# --- 2.6/2.7: distribucion_suave -------------------------------------------


@pytest.mark.parametrize("temperatura", [0.5, 1.0, 2.0])
def test_distribucion_suave_argmax_coincide_con_asignar_clase(temperatura):
    geometria = _geometria_prueba()
    n_obs = np.array([1.577035, 2.1565, 2.096785, 11.68552, 6.0])
    u = np.array([1.0497337983054202, 17.862954277049855, 281.1720793193615, 593.2019276116357, 40.0])

    clase_dura, _ = asignar_clase(n_obs, u, geometria)
    soft = distribucion_suave(n_obs, u, geometria, temperatura=temperatura)

    assert soft.shape == (5, 4)
    np.testing.assert_allclose(soft.sum(axis=-1), 1.0, atol=1e-9)
    np.testing.assert_array_equal(np.argmax(soft, axis=-1), clase_dura)


def test_distribucion_suave_es_no_negativa_y_normalizada():
    geometria = _geometria_prueba()
    soft = distribucion_suave(np.array([3.0]), np.array([0.0]), geometria)
    assert np.all(soft >= 0.0)
    np.testing.assert_allclose(soft.sum(), 1.0, atol=1e-9)
