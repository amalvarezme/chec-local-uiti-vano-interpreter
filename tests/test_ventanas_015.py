"""RED/GREEN tests for PR1 of notebook 01.5 (geometry reuse via 01.4's sha1
guard).

Covers `chec_local_interpreter.ventanas_015.cargar_clases_desde_014`, which
composes `extraer_geometrias_014` -> `verificar_sha1_geometrias` ->
`cargar_geometria_014` -> `asignar_clase` (design section F). No KMeans
fitting happens here -- 01.4's own nearest-centroid geometry is replayed.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-explainability-panel`, requirement "Geometry reuse via
    sha1-guarded 01.4 extractor")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section F)

Uses the same committed fixture as `tests/test_criticality_assignment.py`
and `tests/test_geometrias_sha1.py`
(`tests/fixtures/notebook_01_4_fixture.ipynb`), which embeds the REAL
`espacios`/`grupos`/`geometrias` JSON read from 01.4's committed cell-7
output. `_notebook_tamperado` produces a mutated copy so a sha1 mismatch can
be exercised without ever touching the real 01.4 notebook.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from chec_impacto.models.criticality_assignment import GEOMETRIAS_SHA1_ESPERADO
from chec_local_interpreter import ventanas_015
from chec_local_interpreter.ventanas_015 import cargar_clases_desde_014
from scripts.extract_geometrias_014 import _extraer_bloque_json

FIXTURE_NOTEBOOK = Path(__file__).parent / "fixtures" / "notebook_01_4_fixture.ipynb"

# Raw (n_obs, u) pairs that invert EXACTLY onto each of the four centroids of
# space "2" -- copied from `tests/test_criticality_assignment.py`'s own
# `_PUNTOS_EN_CENTROIDE`, verified independently there against the same
# fixture, so the expected class for each is unambiguous.
_PUNTOS_EN_CENTROIDE = [
    (1.577035, 1.0497337983054202, 0),
    (2.1565, 17.862954277049855, 1),
    (2.096785, 281.1720793193615, 2),
    (11.68552, 593.2019276116357, 3),
]


def _notebook_tamperado(tmp_path: Path) -> Path:
    """Return a copy of the fixture notebook with cell 7's `geometrias`
    block mutated (one centroid nudged), simulating 01.4 being edited so its
    KMeans geometry VALUES changed between two extractions."""
    notebook = json.loads(FIXTURE_NOTEBOOK.read_text(encoding="utf-8"))
    cell = notebook["cells"][7]
    output = next(
        o
        for o in cell["outputs"]
        if o.get("output_type") == "display_data" and "text/html" in o.get("data", {})
    )
    html = "".join(output["data"]["text/html"])

    bloque = _extraer_bloque_json(html, "geometrias")
    geometrias = json.loads(bloque)
    geometrias["2"]["centroides"][0][0] += 1.0
    bloque_tamperado = json.dumps(geometrias)

    output["data"]["text/html"] = [html.replace(bloque, bloque_tamperado, 1)]

    destino = tmp_path / "notebook_01_4_tamperado.ipynb"
    destino.write_text(json.dumps(notebook), encoding="utf-8")
    return destino


# --- 1.1: sha1 mismatch hard-raises ----------------------------------------


def test_cargar_clases_desde_014_raises_on_sha1_mismatch_against_tampered_014(tmp_path):
    notebook_tamperado = _notebook_tamperado(tmp_path)
    geometrias_path = tmp_path / "geometrias_014.json"

    with pytest.raises(RuntimeError) as exc_info:
        cargar_clases_desde_014(
            n_obs=np.array([1.577035]),
            u=np.array([1.0497337983054202]),
            notebook_path=notebook_tamperado,
            geometrias_path=geometrias_path,
        )

    payload = json.loads(geometrias_path.read_text(encoding="utf-8"))
    sha1_real = payload["geometrias_sha1"]
    assert sha1_real != GEOMETRIAS_SHA1_ESPERADO

    mensaje = str(exc_info.value)
    assert GEOMETRIAS_SHA1_ESPERADO in mensaje
    assert sha1_real in mensaje


def test_cargar_clases_desde_014_raises_when_esperado_override_mismatches_real_014(tmp_path):
    """Triangulates the mismatch path with an untampered 01.4 fixture and a
    deliberately wrong `esperado` override, so the RuntimeError is proven to
    come from a real digest comparison, not from special-casing the tampered
    fixture."""
    geometrias_path = tmp_path / "geometrias_014.json"
    esperado_incorrecto = "0" * 40

    with pytest.raises(RuntimeError) as exc_info:
        cargar_clases_desde_014(
            n_obs=np.array([1.577035]),
            u=np.array([1.0497337983054202]),
            notebook_path=FIXTURE_NOTEBOOK,
            geometrias_path=geometrias_path,
            esperado=esperado_incorrecto,
        )

    mensaje = str(exc_info.value)
    assert esperado_incorrecto in mensaje
    assert GEOMETRIAS_SHA1_ESPERADO in mensaje


# --- 1.2: legacy cache missing geometrias_sha1 retries once, then raises ---


def test_cargar_clases_desde_014_retries_legacy_cache_once_then_raises(tmp_path, monkeypatch):
    geometrias_path = tmp_path / "geometrias_014.json"
    geometrias_path.write_text(json.dumps({"grupos": [], "geometrias": {}}), encoding="utf-8")

    llamadas: list[Path] = []

    def _extraccion_legacy(notebook_path, output_path, **kwargs):
        salida = Path(output_path)
        llamadas.append(salida)
        salida.write_text(json.dumps({"grupos": [], "geometrias": {}}), encoding="utf-8")
        return salida

    monkeypatch.setattr(ventanas_015, "extraer_geometrias_014", _extraccion_legacy)

    with pytest.raises(KeyError):
        cargar_clases_desde_014(
            n_obs=np.array([1.0]),
            u=np.array([1.0]),
            notebook_path=FIXTURE_NOTEBOOK,
            geometrias_path=geometrias_path,
        )

    # Re-extraction happens exactly once (retry, not an infinite loop) --
    # the initial `geometrias_path.exists()` branch is skipped since the
    # legacy file was already there, so the only call is the retry.
    assert len(llamadas) == 1


# --- 1.3: 01.4 file missing / extractor RuntimeError propagate uncaught ----


def test_cargar_clases_desde_014_raises_file_not_found_when_014_missing(tmp_path):
    geometrias_path = tmp_path / "geometrias_014.json"
    notebook_inexistente = tmp_path / "no_existe_01_4.ipynb"

    with pytest.raises(FileNotFoundError):
        cargar_clases_desde_014(
            n_obs=np.array([1.0]),
            u=np.array([1.0]),
            notebook_path=notebook_inexistente,
            geometrias_path=geometrias_path,
        )


def test_cargar_clases_desde_014_propagates_extractor_runtime_error_uncaught(tmp_path, monkeypatch):
    geometrias_path = tmp_path / "geometrias_014.json"  # does not exist yet

    def _extraccion_que_falla(notebook_path, output_path, **kwargs):
        raise RuntimeError("01.4 cambio durante la extraccion")

    monkeypatch.setattr(ventanas_015, "extraer_geometrias_014", _extraccion_que_falla)

    with pytest.raises(RuntimeError, match="cambio durante"):
        cargar_clases_desde_014(
            n_obs=np.array([1.0]),
            u=np.array([1.0]),
            notebook_path=FIXTURE_NOTEBOOK,
            geometrias_path=geometrias_path,
        )


# --- 1.4/1.5: GREEN -- matches 01.4's own class assignment -----------------


@pytest.mark.parametrize("n_obs, u, clase_esperada", _PUNTOS_EN_CENTROIDE)
def test_cargar_clases_desde_014_matches_014_geometry_for_known_points(
    tmp_path, n_obs, u, clase_esperada
):
    geometrias_path = tmp_path / "geometrias_014.json"

    clase, n_clamped = cargar_clases_desde_014(
        n_obs=np.array([n_obs]),
        u=np.array([u]),
        notebook_path=FIXTURE_NOTEBOOK,
        geometrias_path=geometrias_path,
    )

    assert clase[0] == clase_esperada
    assert n_clamped == 0


def test_cargar_clases_desde_014_reuses_existing_cache_without_re_extracting(tmp_path, monkeypatch):
    """Once a matching cache exists on disk, no extraction call is needed at
    all -- proves the guard is genuinely cache-aware, not re-extracting on
    every call."""
    geometrias_path = tmp_path / "geometrias_014.json"
    from scripts.extract_geometrias_014 import extraer_geometrias_014 as extraccion_real

    extraccion_real(FIXTURE_NOTEBOOK, geometrias_path)

    def _extraccion_que_no_deberia_llamarse(notebook_path, output_path, **kwargs):
        raise AssertionError("extraer_geometrias_014 no debia llamarse: el cache ya existe")

    monkeypatch.setattr(ventanas_015, "extraer_geometrias_014", _extraccion_que_no_deberia_llamarse)

    clase, n_clamped = cargar_clases_desde_014(
        n_obs=np.array([1.577035]),
        u=np.array([1.0497337983054202]),
        notebook_path=FIXTURE_NOTEBOOK,
        geometrias_path=geometrias_path,
    )

    assert clase[0] == 0
    assert n_clamped == 0
