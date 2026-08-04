"""RED/GREEN tests for notebook 01.5's `ventanas_015` module.

PR1 covers `cargar_clases_desde_014`, which composes
`extraer_geometrias_014` -> `verificar_sha1_geometrias` ->
`cargar_geometria_014` -> `asignar_clase` (design section F). No KMeans
fitting happens here -- 01.4's own nearest-centroid geometry is replayed.

PR3 covers the window builder and the row-1-col-1 (historical map) support
functions: `construir_ventanas` (01.4's own month + shifted-15 cut list,
design section E cell 7), `construir_tabla_vano_ventana` (per-vano x
ventana `num_eventos`/`uiti_acumulado`, 01.4 cell 3's aggregation),
`construir_mask_cache` / `construir_hist_class_cache` (design section A's
`mask_cache` and `hist_class_cache`) and `capas_mapa_historico` (the pure
grouping logic behind row 1 col 1's map traces -- the only piece of that
cell's logic worth testing outside a live kernel, per the Strict TDD rule
that notebook cells only call already-tested functions).

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domains `vano-explainability-panel`)
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (sections A, E, F)

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
import pandas as pd
import pytest

from chec_impacto.models.criticality_assignment import GEOMETRIAS_SHA1_ESPERADO
from chec_local_interpreter import ventanas_015
from chec_local_interpreter.ventanas_015 import (
    cargar_clases_desde_014,
    capas_mapa_historico,
    construir_hist_class_cache,
    construir_mask_cache,
    construir_tabla_vano_ventana,
    construir_ventanas,
)
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


# --- 3.1: construir_ventanas reproduces 01.4's month + shifted-15 cut list -


def test_construir_ventanas_reproduces_01_4_cut_list_for_a_two_month_range():
    """Hand-computed against 01.4's own algorithm (cell 2): each calendar
    month contributes its full span plus the 15th-to-15th crossover into
    the next month; sorted and filtered to the fixed [min, max] range."""
    fechas = pd.to_datetime(["2025-01-05", "2025-01-20", "2025-02-10", "2025-02-25"])

    ventanas = construir_ventanas(fechas)

    assert [v["periodo"] for v in ventanas] == [
        "2025-01-01 a 2025-01-31",
        "2025-01-15 a 2025-02-14",
        "2025-02-01 a 2025-02-28",
    ]
    assert [v["etiqueta"] for v in ventanas] == ["V1", "V2", "V3"]
    assert [v["i"] for v in ventanas] == [0, 1, 2]


def test_construir_ventanas_hasta_excl_is_the_exclusive_upper_bound():
    fechas = pd.to_datetime(["2025-01-05", "2025-02-25"])

    primera = construir_ventanas(fechas)[0]

    assert primera["desde"] == pd.Timestamp("2025-01-01")
    assert primera["hasta_excl"] == pd.Timestamp("2025-02-01")


# --- 3.2: per-(vano, ventana) num_eventos / uiti_acumulado ----------------


def test_construir_tabla_vano_ventana_aggregates_events_per_vano_and_window():
    """Same shape as 01.4 cell 3's `TABLA`: one row per (CIRCUITO,
    FID_VANO, ventana_i) with events, `uiti_acumulado` rounded to 3
    decimals, zero-UITI rows dropped."""
    df = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C2"],
        "FID_VANO": ["VA", "VA", "VB"],
        "UITI_VANO": [1.0, 2.0, 0.5],
        # Jan-03 falls only in window 0; Feb-25 falls only in window 2;
        # Jan-10 falls only in window 0 too (window 1 starts Jan-15).
        "FECHA": pd.to_datetime(["2025-01-03", "2025-02-25", "2025-01-10"]),
    })
    ventanas = construir_ventanas(df["FECHA"])

    tabla = construir_tabla_vano_ventana(df, ventanas)

    fila_va_v0 = tabla[(tabla["FID_VANO"] == "VA") & (tabla["ventana_i"] == 0)].iloc[0]
    assert fila_va_v0["num_eventos"] == 1
    assert fila_va_v0["uiti_acumulado"] == 1.0

    fila_va_v2 = tabla[(tabla["FID_VANO"] == "VA") & (tabla["ventana_i"] == 2)].iloc[0]
    assert fila_va_v2["num_eventos"] == 1
    assert fila_va_v2["uiti_acumulado"] == 2.0

    assert tabla[(tabla["FID_VANO"] == "VA") & (tabla["ventana_i"] == 1)].empty
    assert (tabla["uiti_acumulado"] > 0).all()


# --- 3.2: mask_cache (LRU 64) ----------------------------------------------


def test_construir_mask_cache_returns_boolean_mask_matching_circuito_y_ventana():
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C2"],
        "FID_VANO": ["VA", "VB", "VC"],
        "ventana_i": [0, 1, 0],
        "num_eventos": [1, 1, 1],
        "uiti_acumulado": [1.0, 1.0, 1.0],
    })
    mask_para = construir_mask_cache(tabla)

    mask = mask_para("C1", 0)

    assert mask.tolist() == [True, False, False]
    # Same key returns the SAME cached array object -- proves this is
    # actually `lru_cache`-backed, not recomputing every call.
    assert mask_para("C1", 0) is mask


# --- 3.2: hist_class_cache --------------------------------------------------


def test_construir_hist_class_cache_returns_empty_dict_when_window_has_no_rows():
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1"], "FID_VANO": ["VA"], "ventana_i": [0],
        "num_eventos": [1], "uiti_acumulado": [1.0],
    })
    mask_para = construir_mask_cache(tabla)
    clases_para = construir_hist_class_cache(tabla, mask_para)

    assert clases_para("C1", 1) == {}


def test_construir_hist_class_cache_maps_fid_to_class_via_injected_classifier():
    """`cargar_clases` is injectable so this stays a fast, model/file-free
    unit test -- the real `cargar_clases_desde_014` default is already
    covered end-to-end by the PR1 tests above."""
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1", "C1"], "FID_VANO": ["VA", "VB"], "ventana_i": [0, 0],
        "num_eventos": [1, 5], "uiti_acumulado": [1.0, 9.0],
    })
    mask_para = construir_mask_cache(tabla)
    llamadas = []

    def _clasificador_falso(n_obs, u, **kwargs):
        llamadas.append((tuple(n_obs), tuple(u)))
        return np.where(np.asarray(u) > 5, 3, 0), 0

    clases_para = construir_hist_class_cache(tabla, mask_para, cargar_clases=_clasificador_falso)

    assert clases_para("C1", 0) == {"VA": 0, "VB": 3}
    assert len(llamadas) == 1
    # Cached: a second call with the same key does not invoke the
    # classifier again.
    clases_para("C1", 0)
    assert len(llamadas) == 1


# --- row 1 col 1: capas_mapa_historico --------------------------------------


def test_capas_mapa_historico_groups_by_class_marks_sin_dato_and_halo():
    """The pure layer-grouping logic behind row 1 col 1's map traces
    (design section G, idx 0-5): every vano lands in exactly one class
    layer or `sin_dato`, and marked vanos additionally land in `marcados`
    -- the halo layer. Every returned lat/lon list ends with `None` so
    Plotly draws each vano's segments separately within one trace."""
    geo_circuito = {
        "fids": ["VA", "VB", "VC"],
        "lat": [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]],
        "lon": [[-75.0, -75.1], [-76.0, -76.1], [-77.0, -77.1]],
    }
    clases_por_fid = {"VA": 0, "VB": 3}  # VC absent from the window -> sin_dato

    capas = capas_mapa_historico(geo_circuito, clases_por_fid, marcados=["VB"])

    assert capas["clases"][0]["lat"] == [1.0, 1.1, None]
    assert capas["clases"][3]["lon"] == [-76.0, -76.1, None]
    assert capas["clases"][1] == {"lat": [], "lon": []}
    assert capas["sin_dato"]["lat"] == [3.0, 3.1, None]
    assert capas["marcados"]["lon"] == [-76.0, -76.1, None]
