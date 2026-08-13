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
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chec_impacto.models.criticality_assignment import (
    CLAVE_ESPACIO_CANONICO,
    GEOMETRIAS_SHA1_ESPERADO,
)
from chec_local_interpreter import ventanas_015
from chec_local_interpreter.ventanas_015 import (
    bounds_de_fids,
    cajas_por_cambio_de_grupo,
    cajas_seleccion,
    cargar_clases_desde_014,
    capas_mapa_historico,
    construir_hist_class_cache,
    construir_mask_cache,
    construir_tabla_vano_ventana,
    construir_ventanas,
    nube_fondo,
    nube_seleccion,
    clases_de_series,
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
    # The canonical space is the only one 01.4 exports since 2026-08-09, and its key is
    # read from the constant so this helper follows a renumbering instead of dying on it.
    geometrias[CLAVE_ESPACIO_CANONICO]["centroides"][0][0] += 1.0
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


def test_construir_hist_class_cache_keys_by_str_even_when_fid_vano_is_numeric():
    """The REAL `TABLA` has `FID_VANO` as int64 (it is aggregated straight off
    the CSV), while the map's `GEO_POR_CIRCUITO['fids']` are strings -- the
    shapefile ids go through `str()`. `capas_mapa_historico` looks each geo fid
    up in this dict, so int keys mean EVERY vano misses its class and the whole
    historical map paints "Sin dato". Both this function's annotation and its
    docstring already promise `dict[str, int]`; the fixtures above only ever
    used string fids, so nothing enforced it."""
    tabla = pd.DataFrame({
        "CIRCUITO": ["C1", "C1"], "FID_VANO": [20130434, 20130436], "ventana_i": [0, 0],
        "num_eventos": [1, 5], "uiti_acumulado": [1.0, 9.0],
    })
    assert tabla["FID_VANO"].dtype == "int64"  # como en el cuaderno
    mask_para = construir_mask_cache(tabla)

    clases_para = construir_hist_class_cache(
        tabla, mask_para, cargar_clases=lambda n_obs, u, **kw: (np.where(np.asarray(u) > 5, 3, 0), 0)
    )
    clases = clases_para("C1", 0)

    assert clases == {"20130434": 0, "20130436": 3}
    assert all(isinstance(k, str) for k in clases)


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
    # Una capa sin vanos queda vacia en sus CUATRO columnas (lat/lon mas las
    # dos que PR6 agrego: hovertext y el customdata que resuelve el clic).
    assert capas["clases"][1] == {"lat": [], "lon": [], "hovertext": [], "customdata": []}
    assert capas["sin_dato"]["lat"] == [3.0, 3.1, None]
    assert capas["marcados"]["lon"] == [-76.0, -76.1, None]


def test_capas_mapa_historico_splits_marked_vanos_by_class_and_paints_the_classless_black():
    """Paridad 01.4: un vano MARCADO se dibuja con el color de su clase KMeans, no
    con un color plano de "seleccionado". Un color plano encima de la clase congela
    lo que se ve: mover la ventana cambia la clase por debajo y el vano marcado sigue
    igual en pantalla. El marcado que NO tiene celda en la ventana (sin eventos, o
    ausente de la tabla) va a su propia capa, que el cuaderno pinta de NEGRO -- la
    ausencia de dato no es la clase mas baja."""
    geo_circuito = {
        "fids": ["VA", "VB", "VC"],
        "lat": [[1.0, 1.1], [2.0, 2.1], [3.0, 3.1]],
        "lon": [[-75.0, -75.1], [-76.0, -76.1], [-77.0, -77.1]],
    }
    clases_por_fid = {"VA": 0, "VB": 3}  # VC no tiene celda en la ventana

    capas = capas_mapa_historico(geo_circuito, clases_por_fid, marcados=["VB", "VC"])

    assert capas["marcados_por_clase"][3]["lat"] == [2.0, 2.1, None]
    assert capas["marcados_por_clase"][0]["lat"] == []  # VA tiene clase 0 pero no esta marcado
    assert capas["marcados_sin_dato"]["lat"] == [3.0, 3.1, None]
    # El halo sigue llevando TODOS los marcados: es lo que va debajo, en blanco.
    assert capas["marcados"]["lat"] == [2.0, 2.1, None, 3.0, 3.1, None]
    assert capas["marcados_por_clase"][3]["customdata"] == ["VB", "VB", "VB"]


# --- Caja de seleccion: el rectangulo amarillo del vano marcado --------------


def _geo_cajas():
    return {
        "fids": ["VA", "VB", "VC"],
        # VB es un vano exactamente NORTE-SUR: su longitud no varia, asi que su
        # ancho a traves del trazo es CERO. VC corre a 45 grados exactos, que es
        # donde una caja alineada a los ejes se separa mas de la direccion real.
        "lat": [[1.0, 1.2], [2.0, 2.4], [3.0, 3.1]],
        "lon": [[-75.0, -75.4], [-76.0, -76.0], [-77.0, -77.1]],
    }


def _lados(anillo):
    """Los cuatro lados del anillo como vectores (dlon, dlat)."""
    return [(anillo[i + 1][0] - anillo[i][0], anillo[i + 1][1] - anillo[i][1])
            for i in range(4)]


def _distancia_al_trazo(punto, lon, lat):
    """Distancia con signo del punto a la RECTA del vano, en grados."""
    dlon, dlat = lon[-1] - lon[0], lat[-1] - lat[0]
    largo = math.hypot(dlon, dlat)
    return ((punto[0] - lon[0]) * -dlat + (punto[1] - lat[0]) * dlon) / largo


def test_cajas_seleccion_returns_one_box_per_marked_vano():
    """El resaltado del vano seleccionado es un rectangulo, como un `Polygon`
    GeoJSON que la capa `layout.map.layers` pinta debajo de las trazas. Un
    anillo de GeoJSON se CIERRA -- el ultimo vertice repite el primero --; sin
    eso MapLibre descarta el poligono en silencio y no se dibuja ninguna caja."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VA"], lado_minimo=0.02)

    assert cajas["type"] == "FeatureCollection"
    (feature,) = cajas["features"]
    assert feature["properties"]["fid"] == "VA"
    anillo = feature["geometry"]["coordinates"][0]
    assert feature["geometry"]["type"] == "Polygon"
    assert len(anillo) == 5
    assert anillo[0] == anillo[-1]


def test_cajas_seleccion_gira_la_caja_hasta_la_direccion_del_vano():
    """La caja va INCLINADA como el vano y no alineada a los ejes.

    Sobre un vano diagonal, el rectangulo min/max se sale por las dos esquinas
    que el trazo no toca y encierra tramos vecinos que no son los marcados; el
    usuario termina mirando un cuadro que abarca mas de lo que eligio.

    La prueba dura es contar coordenadas distintas: una caja alineada a los ejes
    solo tiene DOS longitudes y DOS latitudes; una girada tiene cuatro de cada.
    """
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02)

    esquinas = cajas["features"][0]["geometry"]["coordinates"][0][:4]
    assert len({round(lon, 9) for lon, _ in esquinas}) == 4
    assert len({round(lat, 9) for _, lat in esquinas}) == 4
    assert [[round(v, 9) for v in p] for p in esquinas] == [
        [-76.992928932, 3.007071068],
        [-77.092928932, 3.107071068],
        [-77.107071068, 3.092928932],
        [-77.007071068, 2.992928932],
    ]


def test_cajas_seleccion_deja_los_lados_paralelos_y_perpendiculares_al_trazo():
    """Dos lados corren CON el vano y dos lo cruzan en angulo recto: es lo que
    hace que la caja se lea como el resaltado de ese trazo y no como un cuadro
    puesto encima."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VA"], lado_minimo=0.02)

    anillo = cajas["features"][0]["geometry"]["coordinates"][0]
    dlon, dlat = -0.4, 0.2
    paralelos = [abs(a * dlat - b * dlon) for a, b in _lados(anillo)]
    perpendiculares = [abs(a * dlon + b * dlat) for a, b in _lados(anillo)]
    assert sum(v < 1e-12 for v in paralelos) == 2
    assert sum(v < 1e-12 for v in perpendiculares) == 2


def test_cajas_seleccion_abre_lado_minimo_a_lado_y_lado_del_trazo():
    """A traves del vano el ancho es CERO -- un trazo no tiene grosor -- y sobre
    el mapa eso es una franja invisible. `lado_minimo` lo abre de forma SIMETRICA,
    asi que el trazo queda en el eje de la caja y no pegado a un borde."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02)

    esquinas = cajas["features"][0]["geometry"]["coordinates"][0][:4]
    distancias = sorted(round(_distancia_al_trazo(p, [-77.0, -77.1], [3.0, 3.1]), 9)
                        for p in esquinas)
    assert distancias == [-0.01, -0.01, 0.01, 0.01]


def test_cajas_seleccion_de_un_vano_norte_sur_no_cambia_con_el_giro():
    """Un vano exactamente norte-sur ya corria sobre un eje, asi que girar la
    caja a su direccion la deja donde estaba. Se fija para que el giro no se
    cuele como un cambio en los vanos que ya estaban bien."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VB"], lado_minimo=0.001)

    anillo = cajas["features"][0]["geometry"]["coordinates"][0]
    lons = sorted({round(lon, 6) for lon, _ in anillo})
    lats = sorted({round(lat, 6) for _, lat in anillo})
    assert lons == [-76.0005, -75.9995]          # abierta a 0.001 alrededor de -76.0
    assert lats == [2.0, 2.4]                    # el lado que ya medía mas no se toca


def test_cajas_seleccion_adds_the_margin_on_every_side():
    """El margen despega la caja del trazo: sin el, el borde del rectangulo cae
    justo encima de la linea del vano y no se distingue cual es cual. Se agrega
    en el marco DEL VANO, asi que separa lo mismo por los cuatro lados."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02,
                            margen=0.005)

    esquinas = cajas["features"][0]["geometry"]["coordinates"][0][:4]
    distancias = sorted(round(_distancia_al_trazo(p, [-77.0, -77.1], [3.0, 3.1]), 9)
                        for p in esquinas)
    assert distancias == [-0.015, -0.015, 0.015, 0.015]
    # A lo largo el trazo mide 0.141421 grados y la caja lo desborda 0.005 por
    # cada punta, asi que la diagonal sale de 0.151421 por 0.03.
    diagonal = max(math.dist(a, b) for a in esquinas for b in esquinas)
    assert round(diagonal, 6) == round(math.hypot(math.hypot(0.1, 0.1) + 0.01, 0.03), 6)


def test_cajas_seleccion_de_un_vano_sin_largo_vuelve_a_los_ejes():
    """277 de los 60.053 tramos del shapefile tienen sus dos vertices en el MISMO
    punto: no tienen direccion que seguir. Ahi la caja vuelve a alinearse con los
    ejes en vez de fallar o de inventarse un rumbo, que es lo unico honesto que
    se puede dibujar sobre un vano que no apunta a ninguna parte."""
    geo = {"fids": ["VP"], "lat": [[4.0, 4.0]], "lon": [[-75.0, -75.0]]}

    cajas = cajas_seleccion(geo, marcados=["VP"], lado_minimo=0.02)

    anillo = cajas["features"][0]["geometry"]["coordinates"][0]
    assert sorted({round(lon, 9) for lon, _ in anillo}) == [-75.01, -74.99]
    assert sorted({round(lat, 9) for _, lat in anillo}) == [3.99, 4.01]


def test_cajas_seleccion_follows_the_geometry_order_and_ignores_foreign_fids():
    """Recorre la geometria del circuito y no la seleccion: un fid marcado en OTRO
    circuito no tiene coordenadas aqui y no puede producir una caja. Sin esto, la
    seleccion arrastrada de un circuito anterior dibujaria cajas fantasma."""
    cajas = cajas_seleccion(_geo_cajas(), marcados=["VC", "VA", "DE_OTRO_CIRCUITO"])

    assert [f["properties"]["fid"] for f in cajas["features"]] == ["VA", "VC"]


def test_cajas_seleccion_without_marked_vanos_is_an_empty_collection():
    """Sin seleccion la capa sigue existiendo pero no pinta nada. Devolver una
    coleccion VACIA y no `None` es lo que deja que el repintado sea siempre la
    misma escritura, sin quitar y volver a poner la capa del mapa."""
    assert cajas_seleccion(_geo_cajas(), marcados=[]) == {
        "type": "FeatureCollection",
        "features": [],
    }


def test_cajas_seleccion_on_a_circuit_without_geometry_is_empty():
    cajas = cajas_seleccion({"fids": [], "lat": [], "lon": []}, marcados=["VA"])

    assert cajas["features"] == []


# --- Nube KMeans (fila 1 col 3 en 01.4): celdas vano x ventana ---------------


def _tabla_nube():
    return pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2"],
            "FID_VANO": ["VA", "VB", "VA", "VZ"],
            "ventana_i": [0, 0, 1, 0],
            "num_eventos": [1, 5, 9, 3],
            "uiti_acumulado": [0.5, 2.5, 7.5, 1.0],
        }
    )


def test_nube_fondo_groups_every_cell_by_its_class():
    """El fondo de la nube es TODO el dataset y no depende de la seleccion: en 01.4
    el KMeans se ajusta una sola vez y elegir circuito o vanos solo cambia que se
    resalta, nunca donde caen las fronteras."""
    tabla = _tabla_nube()

    capas = nube_fondo(tabla, np.array([0, 2, 3, 0]))

    assert len(capas) == 4
    assert capas[0]["x"] == [1, 3] and capas[0]["y"] == [0.5, 1.0]
    assert capas[2]["x"] == [5] and capas[2]["y"] == [2.5]
    assert capas[1] == {"x": [], "y": []}


def test_nube_seleccion_takes_only_the_marked_cells_of_the_active_window():
    tabla = _tabla_nube()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()

    punto = nube_seleccion(tabla, np.array([0, 2, 3, 0]), mask_ventana=mask_ventana,
                           marcados=["VB"])

    assert punto == {"x": [5], "y": [2.5], "clase": [2], "fid": ["VB"]}


def test_nube_seleccion_without_marked_vanos_takes_the_whole_circuit_window():
    """Mismo criterio que el mapa simulado y el ranking: sin vanos marcados, el grano
    es el circuito completo en esa ventana, no un panel vacio."""
    tabla = _tabla_nube()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()

    punto = nube_seleccion(tabla, np.array([0, 2, 3, 0]), mask_ventana=mask_ventana)

    assert punto["fid"] == ["VA", "VB"]
    assert punto["clase"] == [0, 2]


def test_nube_seleccion_ignores_a_marked_vano_with_no_cell_in_the_window():
    """El vano marcado sin celda en la ventana no tiene punto que dibujar en la nube
    (no existe la fila). Su señal es el NEGRO del mapa, no un punto inventado."""
    tabla = _tabla_nube()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()

    punto = nube_seleccion(tabla, np.array([0, 2, 3, 0]), mask_ventana=mask_ventana,
                           marcados=["VB", "FANTASMA"])

    assert punto["fid"] == ["VB"]


# --- PR6: hover/customdata, recentrado y seleccion por clic -----------------


def test_capas_mapa_historico_carries_fid_and_label_on_every_point():
    """01.4 resolves a map click to a vano by reading the clicked point's
    `customdata`, never by point index -- the segments travel concatenated
    with a `None` separator, so that index shifts with the window. 01.5
    needs the same channel, which means `customdata` has to be exactly as
    long as lat/lon INCLUDING the separator slot, or Plotly misaligns the
    rest of the trace."""
    geo_circuito = {
        "fids": ["VA", "VB", "VC"],
        "lat": [[1.0, 1.1, 1.2], [2.0, 2.1], [3.0, 3.1]],
        "lon": [[-75.0, -75.1, -75.2], [-76.0, -76.1], [-77.0, -77.1]],
    }
    clases_por_fid = {"VA": 0, "VB": 3}

    capas = capas_mapa_historico(
        geo_circuito,
        clases_por_fid,
        marcados=["VB"],
        etiquetas_por_fid={"VA": "vano A", "VB": "vano B", "VC": "vano C"},
    )

    for capa in (capas["clases"][0], capas["clases"][3], capas["sin_dato"], capas["marcados"]):
        assert len(capa["customdata"]) == len(capa["lat"]) == len(capa["lon"])
        assert len(capa["hovertext"]) == len(capa["lat"])

    # Tres puntos mas el separador, y el fid viaja tambien en el separador.
    assert capas["clases"][0]["customdata"] == ["VA"] * 4
    # El separador NO lleva etiqueta: es un hueco, no un punto con hover.
    assert capas["clases"][0]["hovertext"] == ["vano A", "vano A", "vano A", ""]
    assert capas["sin_dato"]["customdata"] == ["VC"] * 3
    assert capas["marcados"]["customdata"] == ["VB"] * 3


def test_capas_mapa_historico_labels_default_to_empty_when_not_given():
    """`etiquetas_por_fid` es opcional: sin ella el hover queda vacio pero
    `customdata` sigue estando, porque el clic no depende del texto."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 2},
    )
    assert capas["clases"][2]["hovertext"] == ["", "", ""]
    assert capas["clases"][2]["customdata"] == ["VA"] * 3


def test_capas_mapa_historico_marks_both_ends_of_every_vano_with_a_horizontal_dash():
    """01's map draws a black horizontal dash on BOTH ends of every vano so the
    extent of each one is readable where two of them meet. It cannot be a marker:
    `marker.symbol` on Scattermap only accepts the map style's sprite icons and
    there is no horizontal-line glyph there. So the dash is two extra 2-point
    segments appended to the SAME layer, which inherit its colour and width."""
    geo_circuito = {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}

    capas = capas_mapa_historico(
        geo_circuito, {"VA": 0}, marca_extremos=0.001,
        etiquetas_por_fid={"VA": "vano A"},
    )

    capa = capas["clases"][0]
    # La polilinea y su separador, y despues un guion por extremo: mismo lat en
    # sus dos puntos (es horizontal), lon corrido media marca a cada lado.
    assert capa["lat"] == [1.0, 1.1, None, 1.0, 1.0, None, 1.1, 1.1, None]
    assert capa["lon"] == [
        -75.0, -75.1, None, -75.001, -74.999, None, -75.101, -75.099, None,
    ]
    # Las cuatro columnas siguen midiendo lo mismo, o Plotly desalinea la traza.
    assert len(capa["customdata"]) == len(capa["hovertext"]) == len(capa["lat"]) == 9
    assert capa["customdata"] == ["VA"] * 9


def test_capas_mapa_historico_dash_points_carry_no_hover_label():
    """El guion NO repite la etiqueta del vano. Medido sobre MVLINSEC: el peor
    circuito pasa de 4.131 a 12.393 puntos al marcar los extremos, y repetir ahi
    una etiqueta de ~130 caracteres agrega ~1 MB a una sola rafaga del comm del
    widget -- por encima del `iopub_data_rate_limit` de 1 MB/s de ipykernel, que
    descarta el mensaje y deja la figura en blanco. No se pierde nada: el vertice
    real del extremo esta en el centro del guion y si lleva la etiqueta."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0},
        marca_extremos=0.001, etiquetas_por_fid={"VA": "vano A"},
    )

    assert capas["clases"][0]["hovertext"] == ["vano A", "vano A", "", *[""] * 6]


def test_capas_mapa_historico_marks_the_ends_of_vanos_without_events_too():
    """Los guiones van en TODOS los vanos, tengan o no eventos en la ventana: son
    la extension del vano, no una senial de su clase."""
    capas = capas_mapa_historico(
        {"fids": ["VA", "VB"], "lat": [[1.0, 1.1], [2.0, 2.1]],
         "lon": [[-75.0, -75.1], [-76.0, -76.1]]},
        {"VA": 0}, marcados=["VB"], marca_extremos=0.001,
    )

    for capa in (capas["clases"][0], capas["sin_dato"], capas["marcados"],
                 capas["marcados_sin_dato"]):
        assert len(capa["lat"]) == 9, capa


def test_capas_mapa_historico_without_marca_extremos_keeps_the_bare_polyline():
    """El parametro es opcional y su default no dibuja ningun guion: el panel web
    densifica y marca en el navegador, donde los puntos no viajan por el comm."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0},
    )

    assert capas["clases"][0]["lat"] == [1.0, 1.1, None]


def test_capas_mapa_historico_densifies_so_hover_lands_anywhere_on_the_vano():
    """El hover de una traza de lineas en Scattermap se resuelve contra los
    VERTICES, no contra la linea: plotly mide la distancia del cursor a cada
    punto y descarta lo que quede a mas de `hoverdistance`. Los tramos de
    MVLINSEC traen EXACTAMENTE dos vertices, asi que a zoom alto el centro de
    un vano no tiene ninguno cerca -- no muestra etiqueta, y como plotly solo
    convierte un clic en evento donde hay hover, tampoco se puede marcar
    tocandolo ahi."""
    largo = 0.01  # ~1,1 km: a zoom 14, 30 px son 143 m, asi que hacen falta cortes
    geo_circuito = {"fids": ["VA"], "lat": [[1.0, 1.0]], "lon": [[-75.0, -75.0 + largo]]}

    capas = capas_mapa_historico(geo_circuito, {"VA": 0}, paso_densificado=0.00022)

    lats = [v for v in capas["clases"][0]["lat"] if v is not None]
    lons = [v for v in capas["clases"][0]["lon"] if v is not None]
    assert len(lons) > 40, len(lons)
    # Los extremos siguen siendo los originales: densificar interpola, no mueve.
    assert lons[0] == pytest.approx(-75.0) and lons[-1] == pytest.approx(-75.0 + largo)
    assert all(v == pytest.approx(1.0) for v in lats)
    # Y ningun hueco mayor al paso pedido, que es lo que da el hover continuo.
    saltos = [abs(b - a) for a, b in zip(lons, lons[1:])]
    assert max(saltos) <= 0.00022 + 1e-12, max(saltos)


def test_capas_mapa_historico_keeps_every_column_aligned_when_densifying():
    """Las cuatro columnas tienen que seguir midiendo lo mismo: si `customdata`
    se desfasa de lat/lon, Plotly desalinea el resto de la traza y el clic
    devuelve el vano equivocado."""
    capas = capas_mapa_historico(
        {"fids": ["VA", "VB"], "lat": [[1.0, 1.02], [2.0, 2.01]],
         "lon": [[-75.0, -75.0], [-76.0, -76.0]]},
        {"VA": 0}, marcados=["VB"], paso_densificado=0.005, marca_extremos=0.001,
    )

    for capa in (capas["clases"][0], capas["sin_dato"], capas["marcados"]):
        assert len(capa["lat"]) == len(capa["lon"]) == len(capa["customdata"]) == len(
            capa["hovertext"])


def test_capas_mapa_historico_carries_extra_columns_in_customdata():
    """Para que el tooltip no repita una etiqueta de ~130 caracteres en CADA
    punto, el hover pasa a `hovertemplate` y lo que viaja por punto son los
    datos crudos del vano. Medido sobre el peor circuito, eso baja la capa de
    2,40 MB a 0,66 MB, y es lo que hace que densificar salga mas barato que lo
    que se mandaba antes. El fid queda SIEMPRE primero: es el canal que
    convierte un clic en un vano."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0},
        datos_por_fid={"VA": (12.5, 3)},
    )

    assert capas["clases"][0]["customdata"] == [["VA", 12.5, 3]] * 3


def test_capas_mapa_historico_without_extra_columns_keeps_the_bare_fid():
    """`datos_por_fid` es opcional: sin el, `customdata` sigue siendo el fid
    suelto, como lo esperan los llamadores que ya existian."""
    capas = capas_mapa_historico(
        {"fids": ["VA"], "lat": [[1.0, 1.1]], "lon": [[-75.0, -75.1]]}, {"VA": 0})

    assert capas["clases"][0]["customdata"] == ["VA", "VA", "VA"]


def test_fid_de_punto_reads_the_fid_from_a_customdata_row():
    """Con columnas extra, `customdata[i]` es una fila y no un escalar; el fid
    sigue siendo su primer elemento."""
    from chec_local_interpreter.ventanas_015 import fid_de_punto

    assert fid_de_punto([["VA", 1.0, 2], ["VB", 3.0, 4]], [1]) == "VB"
    assert fid_de_punto(["VA", "VB"], [0]) == "VA"


def _tamanio_proyectado(bounds, zoom, *, tile=512):
    """El bounding box del circuito, en pixeles, bajo la proyeccion Web Mercator
    que usa MapLibre (teselas de 512 px). Verificado contra el navegador: para
    DON23L13 a zoom 10.1553 predice 328,9 x 389,9 px y Chrome midio 329 x 390."""
    import math

    def merc_y(lat):
        r = math.radians(lat)
        return (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2

    mundo = tile * 2 ** zoom
    return (abs(bounds[3] - bounds[2]) / 360 * mundo,
            abs(merc_y(bounds[0]) - merc_y(bounds[1])) * mundo)


def test_centro_y_zoom_fits_the_circuit_inside_a_wide_short_viewport():
    """Con el tamanio del mapa en pixeles, el encuadre tiene que meter el circuito
    ENTERO adentro -- las dos dimensiones, no solo una.

    La formula anterior derivaba el zoom del span mayor en grados y no sabia nada
    del viewport. Al pasar la figura a ancho completo el mapa quedo en 1553 x 328
    px y medido en el navegador el circuito ocupaba el 21% del ancho y el 119% del
    alto: centrado, pero recortado arriba y abajo. Un grado de latitud y uno de
    longitud no miden lo mismo en pantalla, y menos en un viewport apaisado."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    ancho, alto = 1553, 328
    # DON23L13 y AGU23L15: los dos que se recortaban. bounds = [lat_min, lat_max,
    # lon_min, lon_max].
    for bounds in ([5.49022, 5.68869, -74.80587, -74.66823],
                   [5.02, 5.29, -75.72, -75.63]):
        vista = centro_y_zoom(bounds, ancho_px=ancho, alto_px=alto)

        ancho_circ, alto_circ = _tamanio_proyectado(bounds, vista["zoom"])
        assert ancho_circ <= ancho, (bounds, ancho_circ)
        assert alto_circ <= alto, (bounds, alto_circ)
        # Y que ENTRE no alcanza: tiene que LLENAR la dimension que manda, o el
        # circuito volveria a verse diminuto en el medio.
        assert max(ancho_circ / ancho, alto_circ / alto) > 0.8, (bounds, ancho_circ, alto_circ)


def test_centro_y_zoom_keeps_the_center_of_the_bounding_box():
    """El centro no depende del viewport: solo el zoom."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    bounds = [5.0, 5.2, -75.9, -75.7]
    con_px = centro_y_zoom(bounds, ancho_px=1553, alto_px=328)

    assert con_px["center"] == {"lat": 5.1, "lon": -75.80000000000001}


def test_centro_y_zoom_without_pixel_size_keeps_the_014_formula():
    """El tamanio del viewport es opcional: sin el, la formula historica de 01.4.
    El cuaderno no siempre lo conoce -- con `autosize` el ancho lo decide el
    navegador -- y adivinarlo seria peor que el encuadre aproximado de siempre."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    bounds = [5.0, 5.2, -75.9, -75.7]

    assert centro_y_zoom(bounds)["zoom"] == pytest.approx(10.4137, abs=1e-3)


def test_centro_y_zoom_can_frame_with_the_height_alone():
    """El widget del cuaderno sabe su alto exacto (`height` por el dominio del
    subplot) pero NO su ancho: con `autosize` lo decide el navegador. Encuadrar
    solo por el alto es lo que evita el recorte vertical, que era el defecto;
    que sobre mapa a los lados es el mal menor y ademas se puede paneár."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    bounds = [5.49022, 5.68869, -74.80587, -74.66823]
    alto = 452

    vista = centro_y_zoom(bounds, alto_px=alto)

    _ancho_circ, alto_circ = _tamanio_proyectado(bounds, vista["zoom"])
    assert alto_circ <= alto
    assert alto_circ / alto > 0.8


def test_centro_y_zoom_never_zooms_past_the_tile_limit():
    """Un circuito de un solo vano pediria un zoom sin fin: sigue acotado."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    vista = centro_y_zoom([5.10000, 5.10001, -75.5, -75.49999],
                          ancho_px=1553, alto_px=328)

    assert vista["zoom"] <= 15.0


def test_centro_y_zoom_frames_the_circuit_like_014():
    """Puerto exacto de la formula de 01.4 (celda 7, `map.center`/`map.zoom`):
    centro en el medio del bounding box y zoom por el span mayor, acotado a
    [9, 15]. Un circuito pequenio se acerca; uno enorme no pasa de 9."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    # bounds = [lat_min, lat_max, lon_min, lon_max]
    vista = centro_y_zoom([5.0, 5.2, -75.6, -75.2])
    assert vista["center"] == {"lat": 5.1, "lon": -75.4}
    assert 9.0 <= vista["zoom"] <= 15.0
    # 360/0.4 -> log2 ~= 9.81, menos 0.4 -> 9.41
    assert vista["zoom"] == pytest.approx(9.4139, abs=1e-3)

    # Un circuito diminuto se topa con el techo, no se va a zoom 30.
    assert centro_y_zoom([5.0, 5.00001, -75.0, -75.00001])["zoom"] == 15.0
    # Uno que cubre medio mundo se topa con el piso.
    assert centro_y_zoom([-40.0, 40.0, -100.0, 100.0])["zoom"] == 9.0


def test_centro_y_zoom_rejects_missing_bounds():
    """Sin bounds no hay a donde centrar: devuelve None en vez de inventar
    un centro, para que el llamador deje la vista como estaba."""
    from chec_local_interpreter.ventanas_015 import centro_y_zoom

    assert centro_y_zoom(None) is None
    assert centro_y_zoom([]) is None


def test_fid_de_punto_reads_customdata_not_the_index():
    """El clic devuelve indices de punto dentro de la traza; el fid sale de
    `customdata` en esa posicion. Fuera de rango o sin customdata devuelve
    None en vez de un fid equivocado."""
    from chec_local_interpreter.ventanas_015 import fid_de_punto

    assert fid_de_punto(["VA", "VA", "VA", "VB"], [3]) == "VB"
    assert fid_de_punto(["VA", "VA"], [0]) == "VA"
    assert fid_de_punto(["VA"], []) is None
    assert fid_de_punto(None, [0]) is None
    assert fid_de_punto(["VA"], [7]) is None


# --- Frontera KMeans (Voronoi), evolucion temporal y reparto por grupo -------


def test_frontera_kmeans_partitions_the_plane_by_nearest_centroid():
    """La frontera es el diagrama de Voronoi de los centroides: cada celda de la
    malla toma la clase del centroide mas cercano, con la MISMA funcion que
    clasifica a los vanos. Si se dibujara con otra regla, el contorno diria una
    cosa y los puntos encima otra."""
    from chec_impacto.models.criticality_assignment import Geometria
    from chec_local_interpreter.ventanas_015 import frontera_kmeans

    geometria = Geometria(
        logs=(False, False),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [10.0, 10.0], [20.0, 20.0], [30.0, 30.0]]),
    )

    frontera = frontera_kmeans(geometria, x_min=0.0, x_max=30.0, y_min=0.0, y_max=30.0, n=4)

    assert len(frontera["x"]) == 4 and len(frontera["y"]) == 4
    assert np.asarray(frontera["z"]).shape == (4, 4)  # z[fila_y][columna_x]
    assert frontera["z"][0][0] == 0  # esquina (0,0) -> centroide 0
    assert frontera["z"][-1][-1] == 3  # esquina (30,30) -> centroide 3


def test_frontera_kmeans_spaces_a_logged_axis_geometrically():
    """Un eje logaritmico con malla lineal deja casi todos los puntos apretados en
    la ultima decada y la frontera sale escalonada donde mas se mira."""
    from chec_impacto.models.criticality_assignment import Geometria
    from chec_local_interpreter.ventanas_015 import frontera_kmeans

    geometria = Geometria(
        logs=(False, True),
        offset=np.array([0.0, 0.0]),
        scale=np.array([1.0, 1.0]),
        centroides=np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]),
    )

    frontera = frontera_kmeans(geometria, x_min=1.0, x_max=4.0, y_min=1.0, y_max=1000.0, n=4)

    assert frontera["y"] == pytest.approx([1.0, 10.0, 100.0, 1000.0])
    assert frontera["x"] == pytest.approx([1.0, 2.0, 3.0, 4.0])  # el eje lineal no


def _tabla_series():
    return pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2"],
            "FID_VANO": ["VA", "VA", "VB", "VZ"],
            "ventana_i": [0, 2, 0, 0],
            "num_eventos": [1, 5, 9, 3],
            "uiti_acumulado": [0.5, 2.5, 7.5, 1.0],
        }
    )


def test_series_temporal_vanos_fills_windows_without_a_cell_with_zero():
    """El vano VA no tiene celda en la ventana 1, y eso vale CERO, no un hueco.

    `TABLA` se arma agregando EVENTOS: un vano sin fila en una ventana no es un vano
    sin medir, es un vano sin eventos, y sin eventos el UITI acumulado de esa ventana
    es cero. Con `None` la linea se partia y la secuencia de ventanas se leia como si
    faltara informacion, cuando lo que hay es un cero."""
    from chec_local_interpreter.ventanas_015 import series_temporal_vanos

    series = series_temporal_vanos(_tabla_series(), circuito="C1", fids=["VA"], n_ventanas=3)

    assert len(series) == 1
    assert series[0]["fid"] == "VA"
    assert series[0]["x"] == [0, 1, 2]
    assert series[0]["uiti"] == [0.5, 0.0, 2.5]
    assert series[0]["eventos"] == [1, 0, 5]


def test_series_temporal_vanos_covers_every_window_even_with_no_cells_at_all():
    """La secuencia completa de ventanas se dibuja igual: un vano sin una sola celda
    da una linea en cero de punta a punta, que es lo que dice el dato."""
    from chec_local_interpreter.ventanas_015 import series_temporal_vanos

    series = series_temporal_vanos(_tabla_series(), circuito="C1",
                                   fids=["SIN_EVENTOS"], n_ventanas=4)

    assert series[0]["x"] == [0, 1, 2, 3]
    assert series[0]["uiti"] == [0.0, 0.0, 0.0, 0.0]
    assert series[0]["eventos"] == [0, 0, 0, 0]


def test_series_temporal_vanos_keeps_the_requested_order_and_ignores_other_circuits():
    from chec_local_interpreter.ventanas_015 import series_temporal_vanos

    series = series_temporal_vanos(_tabla_series(), circuito="C1", fids=["VB", "VA"],
                                   n_ventanas=1)

    assert [s["fid"] for s in series] == ["VB", "VA"]
    assert series[0]["uiti"] == [7.5]


def test_reparto_por_clase_describes_only_the_marked_vanos():
    """Regla de 01.4, citada: sin vanos marcados el reparto queda VACIO, no cae al
    circuito entero. Un reparto de miles de vanos y otro de tres se dibujan igual
    pero no dicen lo mismo, y nada en el violin los distingue."""
    from chec_local_interpreter.ventanas_015 import reparto_por_clase

    tabla = _tabla_series()
    mask_ventana = (tabla["CIRCUITO"] == "C1").to_numpy() & (tabla["ventana_i"] == 0).to_numpy()
    clases = np.array([0, 3, 2, 1])

    reparto = reparto_por_clase(tabla, clases, mask_ventana=mask_ventana, marcados=["VB"])
    assert reparto[2] == {"uiti": [7.5], "eventos": [9]}
    assert reparto[0] == {"uiti": [], "eventos": []}

    vacio = reparto_por_clase(tabla, clases, mask_ventana=mask_ventana, marcados=[])
    assert all(grupo == {"uiti": [], "eventos": []} for grupo in vacio)


def test_nube_fondo_subsamples_deterministically_above_the_cap():
    """111.231 celdas en un panel de ~400x300 px son puro sobredibujo, y cada punto
    viaja al navegador por el comm del widget -- 1,2 MB de coordenadas en una sola
    rafaga, por encima del `iopub_data_rate_limit` de 1 MB/s que ipykernel trae por
    defecto. Se submuestrea con semilla FIJA: dos corridas dibujan la misma nube."""
    tabla = pd.DataFrame(
        {
            "CIRCUITO": ["C1"] * 100,
            "FID_VANO": [f"V{i}" for i in range(100)],
            "ventana_i": [0] * 100,
            "num_eventos": list(range(100)),
            "uiti_acumulado": [float(i) for i in range(100)],
        }
    )
    clases = np.array([i % 4 for i in range(100)])

    capas = nube_fondo(tabla, clases, maximo=40)
    otra = nube_fondo(tabla, clases, maximo=40)

    assert sum(len(c["x"]) for c in capas) == 40
    assert [c["x"] for c in capas] == [c["x"] for c in otra]  # misma semilla, misma nube


def test_nube_fondo_draws_everything_below_the_cap():
    tabla = pd.DataFrame(
        {
            "CIRCUITO": ["C1"] * 4,
            "FID_VANO": ["VA", "VB", "VC", "VD"],
            "ventana_i": [0, 0, 0, 0],
            "num_eventos": [1, 2, 3, 4],
            "uiti_acumulado": [0.5, 1.5, 2.5, 3.5],
        }
    )

    capas = nube_fondo(tabla, np.array([0, 0, 1, 1]), maximo=40)

    assert sum(len(c["x"]) for c in capas) == 4
    assert capas[0]["x"] == [1, 2]








def _series_de_prueba():
    return [
        {"fid": "VA", "x": [0, 1, 2],
         "uiti": [1.0, None, 300.0], "eventos": [2, None, 3]},
        {"fid": "VB", "x": [0, 1, 2],
         "uiti": [None, None, None], "eventos": [None, None, None]},
    ]


def _clases_falsas(n_obs, u):
    """Una clase por punto, derivada del UITI para que el orden sea predecible."""
    clase = np.where(np.asarray(u) > 100.0, 3, 0)
    return clase, 0


def test_clases_de_series_gives_one_class_per_drawn_point():
    """El punto de la serie se pinta con el grupo de riesgo de ESE vano en ESA
    ventana, igual que en 03 y 04: la linea dice de que vano es la serie y el
    punto dice en que grupo cayo. Son dos codigos distintos sobre el mismo dato,
    y separarlos por canal -- trazo contra relleno -- es lo que los hace legibles
    a la vez."""
    clases = clases_de_series(_series_de_prueba(), cargar_clases=_clases_falsas)

    assert clases[0] == [0, None, 3]


def test_a_window_without_a_cell_has_no_class_at_all():
    """Sin celda no hay clase, y eso NO es el grupo mas bajo: es la ausencia del
    dato. El panel lo pinta gris, que es distinto del color del grupo 0."""
    clases = clases_de_series(_series_de_prueba(), cargar_clases=_clases_falsas)

    assert clases[0][1] is None
    assert clases[1] == [None, None, None]


def test_every_point_of_every_series_is_classified_in_a_single_call():
    """Con cinco vanos por once ventanas son cincuenta y cinco puntos: clasificarlos
    de a uno serian cincuenta y cinco llamadas a la geometria de 01.4 en cada
    repintado, y el repintado corre en cada clic del mapa."""
    llamadas = []

    def _contar(n_obs, u):
        llamadas.append(len(n_obs))
        return _clases_falsas(n_obs, u)

    clases_de_series(_series_de_prueba(), cargar_clases=_contar)

    assert llamadas == [2]   # los dos unicos puntos con celda, en UNA sola llamada


def test_no_cells_at_all_never_touches_the_geometry():
    """Sin ningun punto con celda no hay nada que clasificar, y llamar igual
    obligaria a la geometria a resolver un arreglo vacio."""
    llamadas = []

    def _contar(n_obs, u):
        llamadas.append(len(n_obs))
        return _clases_falsas(n_obs, u)

    clases = clases_de_series([_series_de_prueba()[1]], cargar_clases=_contar)

    assert llamadas == []
    assert clases == [[None, None, None]]


def test_an_empty_series_list_is_answered_without_work():
    assert clases_de_series([], cargar_clases=_clases_falsas) == []


# --- El recuadro del mapa SIMULADO: tres colores, uno por desenlace -------------------


def _tabla_simulada(filas):
    """La tabla que devuelve `simular_bolsas`, recortada a lo que la caja mira."""
    return pd.DataFrame(
        [{"FID_VANO": fid, "base_clase_idx": base, "simulado_clase_idx": sim,
          "delta_riesgo_ordinal": sim - base} for fid, base, sim in filas]
    )


def test_cajas_por_cambio_de_grupo_separates_the_three_outcomes():
    """El recuadro del mapa simulado ya no dice "este es el vano que elegi" --
    eso lo dice el del mapa base -- sino QUE LE PASO al vano: bajo de grupo,
    se quedo igual, o subio. Son tres capas y no una porque una capa de
    `layout.map.layers` lleva UN color: pintar tres desenlaces en la misma
    capa obligaria a elegir cual de los tres colores miente."""
    tabla = _tabla_simulada([("VA", 2, 0), ("VB", 1, 1), ("VC", 0, 3)])

    cajas = cajas_por_cambio_de_grupo(_geo_cajas(), tabla, marcados=["VA", "VB", "VC"])

    assert [f["properties"]["fid"] for f in cajas["mejora"]["features"]] == ["VA"]
    assert [f["properties"]["fid"] for f in cajas["igual"]["features"]] == ["VB"]
    assert [f["properties"]["fid"] for f in cajas["empeora"]["features"]] == ["VC"]


def test_cajas_por_cambio_de_grupo_only_boxes_the_marked_vanos():
    """La tabla trae una fila por bolsa de la seleccion simulada, pero el
    recuadro senala lo que el usuario ESTA estudiando. Un vano puntuado que no
    esta marcado no lleva caja: si la llevara, marcar un vano y simular todo el
    circuito llenaria el mapa de rectangulos."""
    tabla = _tabla_simulada([("VA", 2, 0), ("VB", 1, 1)])

    cajas = cajas_por_cambio_de_grupo(_geo_cajas(), tabla, marcados=["VA"])

    assert [f["properties"]["fid"] for f in cajas["mejora"]["features"]] == ["VA"]
    assert cajas["igual"]["features"] == []


def test_a_marked_vano_absent_from_the_table_gets_no_box_at_all():
    """Un vano marcado SIN celda en la ventana activa no lo puntuo la simulacion:
    no tiene grupo base ni grupo simulado, asi que no hay desenlace que pintar.
    Meterlo en "igual" seria afirmar que no cambio, que es justamente lo que
    nadie midio."""
    cajas = cajas_por_cambio_de_grupo(
        _geo_cajas(), _tabla_simulada([("VA", 1, 1)]), marcados=["VA", "VC"]
    )

    assert [f["properties"]["fid"] for f in cajas["igual"]["features"]] == ["VA"]
    assert all(
        "VC" not in [f["properties"]["fid"] for f in coleccion["features"]]
        for coleccion in cajas.values()
    )


def test_cajas_por_cambio_de_grupo_keeps_the_three_keys_when_empty():
    """Las tres capas se escriben SIEMPRE, tambien vacias: el repintado es una
    sola escritura por capa y no un quitar y poner capas del mapa, que en
    MapLibre reordena lo que hay debajo."""
    cajas = cajas_por_cambio_de_grupo(_geo_cajas(), _tabla_simulada([]), marcados=["VA"])

    assert sorted(cajas) == ["empeora", "igual", "mejora"]
    assert all(c["type"] == "FeatureCollection" and c["features"] == []
               for c in cajas.values())


def test_cajas_por_cambio_de_grupo_uses_the_same_geometry_as_the_base_box():
    """Mismo rectangulo que el del mapa base, INCLINACION incluida: los dos mapas
    comparten geometria, y dos cajas de forma distinta sobre el mismo vano se
    leerian como dos vanos.

    Se prueba sobre VC, que corre en diagonal, y no sobre un vano norte-sur: ahi
    el rectangulo min/max y el girado coinciden, asi que la prueba pasaria aunque
    el mapa simulado se hubiera quedado con la caja alineada a los ejes."""
    tabla = _tabla_simulada([("VC", 1, 1)])

    cajas = cajas_por_cambio_de_grupo(
        _geo_cajas(), tabla, marcados=["VC"], lado_minimo=0.02, margen=0.005
    )
    base = cajas_seleccion(_geo_cajas(), marcados=["VC"], lado_minimo=0.02, margen=0.005)

    assert cajas["igual"]["features"] == base["features"]
    esquinas = cajas["igual"]["features"][0]["geometry"]["coordinates"][0][:4]
    assert len({round(lon, 9) for lon, _ in esquinas}) == 4


# --- El encuadre del mapa simulado sobre los vanos elegidos ---------------------------


def test_bounds_de_fids_frames_only_the_given_vanos():
    """El mapa simulado se centra sobre los vanos que se estan estudiando y no
    sobre el circuito entero: despues de simular, la pregunta es que le paso a
    ESOS vanos, y buscarlos otra vez dentro del garabato completo es trabajo
    que el tablero puede ahorrar."""
    assert bounds_de_fids(_geo_cajas(), ["VA"]) == (1.0, 1.2, -75.4, -75.0)


def test_bounds_de_fids_covers_every_vano_of_the_selection():
    """Con varios vanos el encuadre los tiene que contener a TODOS: encuadrar
    sobre el primero dejaria los demas fuera de pantalla."""
    assert bounds_de_fids(_geo_cajas(), ["VA", "VC"]) == (1.0, 3.1, -77.1, -75.0)


def test_bounds_de_fids_without_coordinates_is_none():
    """Sin fids -- o con fids de otro circuito -- devuelve None para que el
    llamador deje el encuadre donde estaba, en vez de centrar en un punto
    inventado. Es el mismo contrato que `centro_y_zoom` con bounds vacios."""
    assert bounds_de_fids(_geo_cajas(), []) is None
    assert bounds_de_fids(_geo_cajas(), ["DE_OTRO_CIRCUITO"]) is None


def test_clases_de_series_gives_no_class_to_a_window_with_zero_events():
    """Cero eventos no es el grupo mas bajo: es la ausencia del dato. La geometria de
    01.4 vive en (n_obs, log10 u), y log10(0) no existe, asi que ese punto no se puede
    clasificar -- el panel lo pinta gris."""
    from chec_local_interpreter.ventanas_015 import clases_de_series

    series = [{"x": [0, 1], "uiti": [0.0, 2.5], "eventos": [0, 5]}]
    llamadas = []

    def _clases(n_obs, u, **kwargs):
        llamadas.append(len(n_obs))
        return np.zeros(len(n_obs), dtype=int), 0

    clases = clases_de_series(series, cargar_clases=_clases)

    assert clases == [[None, 0]]
    assert llamadas == [1]  # la ventana en cero no se manda a clasificar


# --- Que vanos entran al diagnostico del cuaderno 06 -----------------------------------
# El boton "Diagnostico" ya no describe SIEMPRE el top del circuito: parte de lo que el
# usuario marco -- por casilla o por clic en el mapa -- y completa con los de mayor UITI
# de la ventana hasta el tope. La regla vive aqui y no en la celda del cuaderno porque es
# la decision de QUE se diagnostica, no cableado de widgets: se puede equivocar en
# silencio y por eso se prueba con datos, no leyendo el fuente.


def _datos_ventana():
    """UITI y eventos por vano en UNA ventana, como los arma `DATOS_VENTANA`."""
    return {
        "V1": (10.0, 3),
        "V2": (9.0, 2),
        "V3": (8.0, 5),
        "V4": (7.0, 1),
        "V5": (6.0, 4),
    }


def test_el_diagnostico_sin_marcados_toma_el_top_por_uiti_y_cuenta_lo_que_deja_fuera():
    """Sin nada marcado la pregunta es por donde empezar en el circuito, y la respuesta
    son los de mayor UITI. Lo que no cabe se CUENTA: una lista de tres sobre un circuito
    con cinco vanos con eventos se lee como que el circuito tiene tres."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5"], marcados=[], maximo=3)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V1", "V2", "V3"]
    assert elegidos["marcados"] == []
    assert elegidos["completados"] == ["V1", "V2", "V3"]
    assert elegidos["restantes"] == 2
    assert elegidos["con_eventos"] == 5


def test_el_diagnostico_no_recorta_cuando_el_circuito_tiene_menos_que_el_tope():
    """Con menos vanos con eventos que el tope no queda nada fuera, y `restantes` en
    cero es lo que apaga el aviso del panel."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(_datos_ventana(), ["V1", "V2"], maximo=15)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V1", "V2"]
    assert elegidos["restantes"] == 0


def test_lo_marcado_manda_y_el_resto_se_completa_por_uiti():
    """El vano que el usuario marco entra aunque no sea de los de mayor UITI -- es la
    orden de trabajo que tiene en la mano --, y el cupo que sobra se llena con los mas
    altos de la ventana, sin repetir los que ya estaban."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5"], marcados=["V5", "V4"], maximo=4)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V4", "V5", "V1", "V2"]
    assert elegidos["marcados"] == ["V4", "V5"]      # los del usuario, por UITI
    assert elegidos["completados"] == ["V1", "V2"]   # el relleno, sin repetir
    assert elegidos["restantes"] == 1                # V3 queda con eventos y fuera


def test_un_vano_marcado_sin_eventos_se_nombra_y_no_gasta_cupo():
    """Sin celda en la ventana el modelo no lo puede puntuar: entra a `sin_eventos` para
    que el panel lo diga, y su lugar lo ocupa un vano que si se puede diagnosticar."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5", "V9"],
        marcados=["V9", "V5"], maximo=3)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V5", "V1", "V2"]
    assert elegidos["sin_eventos"] == ["V9"]
    assert elegidos["con_eventos"] == 5


def test_marcar_mas_que_el_tope_deja_los_de_mayor_uiti_de_lo_marcado():
    """El selector topa en el mismo numero, asi que este caso solo llega por codigo. Se
    resuelve como el resto: manda el UITI, y lo que se cae se cuenta."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        _datos_ventana(), ["V1", "V2", "V3", "V4", "V5"],
        marcados=["V3", "V4", "V5"], maximo=2)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["V3", "V4"]
    assert elegidos["completados"] == []
    assert elegidos["restantes"] == 3


def test_el_diagnostico_compara_los_fid_como_texto():
    """`DATOS_VENTANA` esta indexado por TEXTO y tanto `VANOS_POR_CIRCUITO` como las
    casillas pueden traer el fid como numero. Sin la coercion no coincide ninguno y el
    diagnostico sale vacio sin decir por que."""
    from chec_local_interpreter.ventanas_015 import vanos_para_diagnostico

    elegidos = vanos_para_diagnostico(
        {"7001": (5.0, 2), "7002": (4.0, 1)}, [7001, 7002], marcados=[7002], maximo=2)

    assert [f for f, _u, _n in elegidos["vanos"]] == ["7002", "7001"]
    assert elegidos["marcados"] == ["7002"]
