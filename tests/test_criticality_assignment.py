"""RED/GREEN tests for D6 (criticality assignment from 01.4's KMeans geometry).

Covers `chec_impacto.models.criticality_assignment`: `Geometria`,
`cargar_geometria_014`, `verificar_sha1_geometrias`, `asignar_clase`,
`distribucion_suave`.

See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain
    `criticality-assignment-from-014`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D6)
  - geometry re-sourcing: `sdd/retire-base-apps-notebooks/spec` (domain
    `criticidad-geometria`), `sdd/retire-base-apps-notebooks/design` (D3)

Retired (`sdd/retire-base-apps-notebooks`): this file used to build its test
fixtures by running `scripts.extract_geometrias_014.extraer_geometrias_014`
against a committed notebook fixture. That script is deleted -- the geometry
is now a tracked artifact (`data/geometria_kmeans_014_v1.json`), so these
tests build small JSON fixtures directly instead. The numeric values below
are the SAME real values the retired extraction used to produce (verified
independently: `tests/test_geometria_kmeans_promovida.py` cross-checks the
committed artifact against `data/models/mil_vano_ventana_v1.pt`), not
fabricated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from chec_impacto.models.criticality_assignment import (
    CLAVE_ESPACIO_CANONICO,
    EPS_UITI,
    GEOMETRIAS_SHA1_ESPERADO,
    Geometria,
    asignar_clase,
    cargar_geometria_014,
    distribucion_suave,
    verificar_sha1_geometrias,
)

# Real values for the canonical space (log_x=False, log_y=True, prep="minmax"), taken
# from the tracked artifact `data/geometria_kmeans_014_v1.json` -- NOT fabricated. They
# are UNCHANGED since: on 2026-08-09 the space stopped being a control and its key moved
# from "2" to "0", but the fit -- same data, same seed, same space -- produced the same
# numbers.
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


def _sha1_de_geometrias(geometrias: dict) -> str:
    """Same canonicalization the retired `extract_geometrias_014.py` used:
    sorted-key, no-whitespace JSON over the `geometrias` block only."""
    canonical = json.dumps(geometrias, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _geometria_prueba() -> Geometria:
    return Geometria(
        logs=GEOMETRIA_CANONICA_ESPERADA["logs"],
        offset=np.array(GEOMETRIA_CANONICA_ESPERADA["offset"]),
        scale=np.array(GEOMETRIA_CANONICA_ESPERADA["scale"]),
        centroides=np.array(GEOMETRIA_CANONICA_ESPERADA["centroides"]),
    )


def _escribir_geometrias_json(destino: Path, geometrias: dict) -> Path:
    payload = {
        "grupos": ["Bajo", "Medio", "Medio-Alto", "Alto"],
        "geometrias": geometrias,
        "geometrias_sha1": _sha1_de_geometrias(geometrias),
    }
    destino.write_text(json.dumps(payload), encoding="utf-8")
    return destino


# --- 2.1/2.2/2.3: loader ----------------------------------------------------


def test_cargar_geometria_014_desde_json(tmp_path):
    salida = _escribir_geometrias_json(
        tmp_path / "geometrias_014.json", {CLAVE_ESPACIO_CANONICO: GEOMETRIA_CANONICA_ESPERADA}
    )

    geometria = cargar_geometria_014(salida, clave=CLAVE_ESPACIO_CANONICO)

    assert geometria.logs == GEOMETRIA_CANONICA_ESPERADA["logs"]
    np.testing.assert_allclose(geometria.offset, GEOMETRIA_CANONICA_ESPERADA["offset"])
    np.testing.assert_allclose(geometria.scale, GEOMETRIA_CANONICA_ESPERADA["scale"])
    np.testing.assert_allclose(geometria.centroides, GEOMETRIA_CANONICA_ESPERADA["centroides"])
    assert geometria.centroides.shape == (4, 2)


def test_cargar_geometria_014_clave_ausente_lanza(tmp_path):
    salida = _escribir_geometrias_json(
        tmp_path / "geometrias_014.json", {CLAVE_ESPACIO_CANONICO: GEOMETRIA_CANONICA_ESPERADA}
    )
    with pytest.raises(KeyError):
        cargar_geometria_014(salida, clave="99")


# --- verificar_sha1_geometrias: pin match / mismatch / legacy payload ------
# (folded in from the retired `tests/test_geometrias_sha1.py`, which tested
# this same function via extraction; the fixtures below reproduce the SAME
# canonical geometry directly instead.)


def test_verificar_sha1_geometrias_matches_pinned_constant_on_real_geometry(tmp_path):
    """The fixture embeds the REAL canonical geometry, so verifying it
    against the pinned expected constant must report a match."""
    salida = _escribir_geometrias_json(
        tmp_path / "geometrias_014.json", {CLAVE_ESPACIO_CANONICO: GEOMETRIA_CANONICA_ESPERADA}
    )

    sha1_real, coincide = verificar_sha1_geometrias(salida)
    assert coincide is True
    assert sha1_real == GEOMETRIAS_SHA1_ESPERADO


def test_verificar_sha1_geometrias_reports_mismatch_against_wrong_expected(tmp_path):
    salida = _escribir_geometrias_json(
        tmp_path / "geometrias_014.json", {CLAVE_ESPACIO_CANONICO: GEOMETRIA_CANONICA_ESPERADA}
    )

    sha1_real, coincide = verificar_sha1_geometrias(salida, esperado="0" * 40)
    assert coincide is False
    assert sha1_real == GEOMETRIAS_SHA1_ESPERADO


def test_verificar_sha1_geometrias_raises_on_legacy_payload_without_field(tmp_path):
    salida = tmp_path / "geometrias_014_legacy.json"
    salida.write_text(json.dumps({"grupos": [], "geometrias": {}}), encoding="utf-8")

    with pytest.raises(KeyError):
        verificar_sha1_geometrias(salida)


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
