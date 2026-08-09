"""Historical vano criticality classes and window/map support for notebook
01.5.

PR1: 01.5's row-1 (historical) classes are NEVER re-fit here. This module
composes the same read-only chain notebook 10 already uses --
`extraer_geometrias_014` -> `verificar_sha1_geometrias` ->
`cargar_geometria_014` -> `asignar_clase` -- so 01.4's own nearest-centroid
KMeans assignment is replayed exactly, and a future edit to 01.4 that moves
the centroids fails loudly instead of silently drifting downstream classes.

PR3: `construir_ventanas` and `construir_tabla_vano_ventana` reproduce
01.4's own window cut list and per-(vano, ventana) event aggregation
verbatim (design section E, cells 3 and 7). `construir_mask_cache` and
`construir_hist_class_cache` are the session-scoped, `lru_cache`-backed
caches design section A calls `mask_cache` and `hist_class_cache`.
`capas_mapa_historico` is the pure grouping logic behind row 1 col 1's map
traces (design section G) -- the only part of that notebook cell worth
testing outside a live kernel; the cell itself only calls it.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-explainability-panel`)
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (sections A, E, F, G)
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from chec_impacto.models.criticality_assignment import (
    CLAVE_ESPACIO_CANONICO,
    GEOMETRIAS_SHA1_ESPERADO,
    asignar_clase,
    cargar_geometria_014,
    verificar_sha1_geometrias,
)
from scripts.extract_geometrias_014 import (
    DEFAULT_NOTEBOOK_PATH,
    DEFAULT_OUTPUT_PATH,
    extraer_geometrias_014,
)


def cargar_clases_desde_014(
    n_obs: np.ndarray,
    u: np.ndarray,
    *,
    notebook_path: str | Path = DEFAULT_NOTEBOOK_PATH,
    geometrias_path: str | Path = DEFAULT_OUTPUT_PATH,
    clave: str = CLAVE_ESPACIO_CANONICO,
    esperado: str = GEOMETRIAS_SHA1_ESPERADO,
) -> tuple[np.ndarray, int]:
    """Assign historical criticality classes for `(n_obs, u)` pairs, reusing
    01.4's own KMeans geometry.

    Composes `extraer_geometrias_014` -> `verificar_sha1_geometrias` ->
    `cargar_geometria_014` -> `asignar_clase` (design section F):

      - If `geometrias_path` does not exist yet, it is produced by a
        read-only `extraer_geometrias_014` pass over `notebook_path`. A
        missing `notebook_path` raises `FileNotFoundError`; a notebook that
        mutates mid-read raises `RuntimeError`. Both propagate uncaught.
      - A legacy cache missing the `geometrias_sha1` field raises `KeyError`
        from `verificar_sha1_geometrias`; that is caught exactly once, the
        stale file is deleted, extraction re-runs, and verification is
        retried. A second failure propagates uncaught.
      - A sha1 mismatch against `esperado` raises `RuntimeError` carrying
        both digests -- 01.4 was edited and its centroids moved, so
        continuing silently would shift every downstream criticality class.

    Returns the same `(clase, n_clamped)` pair as `asignar_clase`.
    """
    notebook_path = Path(notebook_path)
    geometrias_path = Path(geometrias_path)

    if not geometrias_path.exists():
        extraer_geometrias_014(notebook_path, geometrias_path)

    try:
        sha1_real, coincide = verificar_sha1_geometrias(geometrias_path, esperado=esperado)
    except KeyError:
        geometrias_path.unlink()
        extraer_geometrias_014(notebook_path, geometrias_path)
        sha1_real, coincide = verificar_sha1_geometrias(geometrias_path, esperado=esperado)

    if not coincide:
        raise RuntimeError(
            "La geometria KMeans extraida de 01.4 no coincide con la esperada "
            f"(esperado={esperado}, real={sha1_real}). 01.4 fue modificado; "
            "01.5 y el cuaderno 10 dependen de esa geometria."
        )

    geometria = cargar_geometria_014(geometrias_path, clave)
    return asignar_clase(n_obs, u, geometria)


def construir_ventanas(fechas: pd.Series | np.ndarray) -> list[dict[str, Any]]:
    """01.4's own window cut list (cell 2), reproduced verbatim: each
    calendar month contributes its full span AND the 15th-to-15th crossover
    into the next month, interleaved and sorted, over the fixed
    `[fechas.min(), fechas.max()]` range. Identical to 01.3's windows.

    Returns a list of `{'i', 'desde', 'hasta_excl', 'etiqueta', 'periodo'}`
    dicts, `hasta_excl` being the exclusive upper bound row filters use.
    """
    fechas = pd.to_datetime(pd.Series(fechas)).dropna()
    meses = pd.period_range(fechas.min(), fechas.max(), freq="M")
    fin = meses[-1].to_timestamp(how="end").normalize() + pd.Timedelta(days=1)

    cortes: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for k, m in enumerate(meses):
        ini = m.to_timestamp()
        f = meses[k + 1].to_timestamp() if k + 1 < len(meses) else fin
        cortes.append((ini, f))
        cortes.append((ini + pd.Timedelta(days=14), f + pd.Timedelta(days=14)))
    cortes = sorted(c for c in cortes if c[1] <= fin)

    return [
        {
            "i": k,
            "desde": a,
            "hasta_excl": b,
            "etiqueta": f"V{k + 1}",
            "periodo": f"{a.date()} a {(b - pd.Timedelta(days=1)).date()}",
        }
        for k, (a, b) in enumerate(cortes)
    ]


def construir_tabla_vano_ventana(
    df: pd.DataFrame, ventanas: Iterable[Mapping[str, Any]]
) -> pd.DataFrame:
    """01.4's own per-(vano, ventana) aggregation (cell 3), reproduced
    verbatim: one row per (CIRCUITO, FID_VANO, ventana) with events,
    `uiti_acumulado` rounded to 3 decimals, zero-UITI rows dropped.
    Windows are not calendar months, so each is filtered separately --
    they cannot simply be summed.
    """
    piezas = []
    for v in ventanas:
        dentro = df[(df["FECHA"] >= v["desde"]) & (df["FECHA"] < v["hasta_excl"])]
        agg = (
            dentro.groupby(["CIRCUITO", "FID_VANO"])["UITI_VANO"]
            .agg(uiti_acumulado="sum", num_eventos="count")
            .reset_index()
        )
        agg["ventana"] = v["etiqueta"]
        agg["ventana_i"] = v["i"]
        piezas.append(agg)

    tabla = pd.concat(piezas, ignore_index=True)
    tabla["uiti_acumulado"] = tabla["uiti_acumulado"].round(3)
    tabla = tabla[tabla["uiti_acumulado"] > 0].reset_index(drop=True)
    return tabla.sort_values(["CIRCUITO", "FID_VANO", "ventana_i"]).reset_index(drop=True)


def construir_mask_cache(
    tabla: pd.DataFrame, *, maxsize: int = 64
) -> Callable[[str, int], np.ndarray]:
    """Design section A's `mask_cache`: a session-scoped, `lru_cache`d
    `(circuito, ventana_i) -> boolean row mask` over `tabla`. Never
    invalidated -- it is a pure function of `tabla`'s own CIRCUITO and
    ventana_i columns, which never change once built.
    """
    circuitos = tabla["CIRCUITO"].to_numpy()
    ventanas_i = tabla["ventana_i"].to_numpy()

    @lru_cache(maxsize=maxsize)
    def mask_para(circuito: str, ventana_i: int) -> np.ndarray:
        return (circuitos == circuito) & (ventanas_i == ventana_i)

    return mask_para


def construir_hist_class_cache(
    tabla: pd.DataFrame,
    mask_para: Callable[[str, int], np.ndarray],
    *,
    maxsize: int = 64,
    cargar_clases: Callable[..., tuple[np.ndarray, int]] = cargar_clases_desde_014,
    **cargar_clases_kwargs: Any,
) -> Callable[[str, int], dict[str, int]]:
    """Design section A's `hist_class_cache`: a session-scoped, `lru_cache`d
    `(circuito, ventana_i) -> {FID_VANO: clase}` map, built by running
    `cargar_clases` (defaults to `cargar_clases_desde_014`, injectable for
    tests) over exactly the rows `mask_para` selects. A window with zero
    rows for the circuit returns `{}` -- every fid absent from the result
    is "sin dato" for that window, never a fabricated class.
    """
    fids = tabla["FID_VANO"].to_numpy()

    @lru_cache(maxsize=maxsize)
    def clases_para(circuito: str, ventana_i: int) -> dict[str, int]:
        mask = mask_para(circuito, ventana_i)
        if not mask.any():
            return {}
        n_obs = tabla.loc[mask, "num_eventos"].to_numpy(dtype=float)
        u = tabla.loc[mask, "uiti_acumulado"].to_numpy(dtype=float)
        clase, _n_clamped = cargar_clases(n_obs, u, **cargar_clases_kwargs)
        # `str(fid)` y no el valor crudo: en el cuaderno `TABLA['FID_VANO']` es int64
        # (sale de agregar el CSV) mientras que los fids del mapa son STRINGS (vienen
        # del shapefile via `str()`). `capas_mapa_historico` busca cada fid geografico
        # en este diccionario, asi que con llaves int no coincide NINGUNO y el mapa
        # historico entero se pinta de "Sin dato". Es la misma coercion que ya hace
        # `clases_por_fid_desde_resultado` para la fila 2.
        return {str(fid): int(c) for fid, c in zip(fids[mask].tolist(), clase.tolist())}

    return clases_para


def capas_mapa_historico(
    geo_circuito: Mapping[str, Any],
    clases_por_fid: Mapping[str, int],
    *,
    marcados: Iterable[str] = (),
    etiquetas_por_fid: Mapping[str, str] | None = None,
    marca_extremos: float = 0.0,
    paso_densificado: float = 0.0,
    datos_por_fid: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    """The pure layer-grouping logic behind row 1 col 1's map traces
    (design section G, idx 0-5): given one circuit's vano polylines
    (`geo_circuito`, 01.4's own `GEO_POR_CIRCUITO[circuito]` shape --
    `{'fids', 'lat', 'lon'}`, lat/lon one list of coordinates per fid) and
    `clases_por_fid` (a `hist_class_cache` result), groups every vano into
    exactly one of: a class layer (0-3), or `sin_dato` (fid absent from
    `clases_por_fid` -- no event-row in the active window). Marked vanos
    additionally land in `marcados`, the halo layer.

    Each returned lat/lon list is flat with a trailing `None` after every
    vano's coordinates, so Plotly draws each vano's segments separately
    within a single `Scattermap` trace instead of connecting them.

    Every layer also carries `customdata` (the fid of each point) and
    `hovertext` (`etiquetas_por_fid[fid]`, empty when not supplied). The fid
    travels in the separator slot too: 01.4 learned that `customdata` has to
    measure exactly what lat/lon measure or Plotly misaligns the rest of the
    trace. That column is what turns a map click into a vano -- resolving it
    by point index would be fragile, because the index moves with the window.

    Marked vanos additionally land in three places (01.4 parity): `marcados`
    (every marked vano -- the white halo drawn UNDER the rest), plus either
    `marcados_por_clase[clase]` or `marcados_sin_dato` for the coloured line
    on top. Splitting them is what keeps a marked vano readable: painting the
    selection in one flat colour on top of the class colour freezes what the
    eye sees, so moving the window changes the class underneath and the marked
    vano looks identical. `marcados_sin_dato` is the marked vano with NO cell
    in the active window, which the notebook paints black -- absence of data,
    not the lowest class.

    `marca_extremos` (degrees of longitude, 0 = off) adds 01's end-of-vano dash
    to every vano of every layer -- see `_agregar_tramo`. `paso_densificado`
    (degrees, 0 = off) interpolates vertices so hover and click reach the whole
    vano and not just its ends -- see `_densificar`.

    `datos_por_fid` appends that vano's raw columns after the fid in
    `customdata`, so the caller can drive a per-trace `hovertemplate` instead of
    repeating a formatted label at every point. Measured on the worst circuit,
    that is the difference between 2,40 MB and 0,66 MB per layer, and it is what
    makes densifying cheaper than what was travelling before.
    """
    etiquetas_por_fid = etiquetas_por_fid or {}
    capas: dict[int, dict[str, list]] = {clase: _capa_vacia() for clase in range(4)}
    sin_dato = _capa_vacia()
    marcados_capa = _capa_vacia()
    marcados_por_clase: dict[int, dict[str, list]] = {
        clase: _capa_vacia() for clase in range(4)
    }
    marcados_sin_dato = _capa_vacia()
    marcados = set(marcados)

    for fid, lat, lon in zip(geo_circuito["fids"], geo_circuito["lat"], geo_circuito["lon"]):
        clase = clases_por_fid.get(fid)
        etiqueta = etiquetas_por_fid.get(fid, "")
        datos = None if datos_por_fid is None else list(datos_por_fid.get(fid, ()))
        extra = (marca_extremos, paso_densificado, datos)
        _agregar_tramo(capas.get(clase, sin_dato), fid, lat, lon, etiqueta, *extra)
        if fid in marcados:
            _agregar_tramo(marcados_capa, fid, lat, lon, etiqueta, *extra)
            _agregar_tramo(
                marcados_por_clase.get(clase, marcados_sin_dato),
                fid, lat, lon, etiqueta, *extra,
            )

    return {
        "clases": capas,
        "sin_dato": sin_dato,
        "marcados": marcados_capa,
        "marcados_por_clase": marcados_por_clase,
        "marcados_sin_dato": marcados_sin_dato,
    }


MAX_PUNTOS_NUBE = 20_000


def nube_fondo(
    tabla: pd.DataFrame,
    clase_por_fila: np.ndarray,
    *,
    maximo: int = MAX_PUNTOS_NUBE,
    semilla: int = 42,
) -> list[dict[str, list[float]]]:
    """01.4's KMeans cloud background: the (vano, ventana) cells of `tabla` as
    points `(num_eventos, uiti_acumulado)`, grouped into the 4 class layers by
    `clase_por_fila` (one class per row of `tabla`, in row order).

    It never depends on the selection: 01.4 fits KMeans once over all cells,
    so choosing a circuit or marking vanos only changes what is highlighted,
    never where the boundaries fall. Computing it once and only restyling the
    highlight is what keeps the panel free at interaction time.

    Above `maximo` rows the cloud is SUBSAMPLED uniformly with a fixed seed.
    Two reasons, and the second is the one that bites: 111k points inside a
    ~400x300 px panel is pure overplotting, and every one of them travels to
    the browser through the widget comm -- over a megabyte of coordinates in a
    single burst, past the 1 MB/s `iopub_data_rate_limit` ipykernel ships by
    default, which drops the message and leaves the figure blank. The sample
    is uniform over rows (not stratified by class) so the visual density stays
    proportional, and the seed is fixed so two runs draw the same cloud.
    """
    clase_por_fila = np.asarray(clase_por_fila)
    x = tabla["num_eventos"].to_numpy()
    y = tabla["uiti_acumulado"].to_numpy()

    n = len(x)
    if n > int(maximo):
        elegidos = np.sort(
            np.random.default_rng(semilla).choice(n, size=int(maximo), replace=False)
        )
        x, y, clase_por_fila = x[elegidos], y[elegidos], clase_por_fila[elegidos]

    capas = []
    for clase in range(4):
        mask = clase_por_fila == clase
        # Redondeo explicito: el UITI ya viene a 3 decimales de
        # `construir_tabla_vano_ventana`, pero un float64 se serializa con toda su
        # cola y el panel no distingue el cuarto decimal.
        capas.append(
            {
                "x": np.round(x[mask], 3).tolist(),
                "y": np.round(y[mask], 3).tolist(),
            }
        )
    return capas


def frontera_kmeans(
    geometria: Any,
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    n: int = 90,
) -> dict[str, Any]:
    """The Voronoi partition of the `(eventos, UITI)` plane under 01.4's
    KMeans geometry: an `n x n` grid whose every cell carries the class of its
    NEAREST centroid, ready for a filled `go.Contour` underneath the cloud.

    The grid is scored with `asignar_clase` -- the same function that
    classifies the vanos themselves. Reimplementing the boundary with its own
    distance rule is how a contour ends up disagreeing with the very points
    drawn on top of it.

    A logged axis is spaced GEOMETRICALLY. On a log axis a linear grid packs
    almost every sample into the last decade, so the boundary comes out
    stair-stepped exactly where the eye is looking.

    Returns `{'x', 'y', 'z'}` with `z[fila_y][columna_x]`, Plotly's own
    orientation for `Contour`.
    """
    log_x, log_y = (bool(v) for v in geometria.logs)
    eje_x = (
        np.geomspace(max(float(x_min), 1e-6), float(x_max), n)
        if log_x else np.linspace(float(x_min), float(x_max), n)
    )
    eje_y = (
        np.geomspace(max(float(y_min), 1e-6), float(y_max), n)
        if log_y else np.linspace(float(y_min), float(y_max), n)
    )
    malla_x, malla_y = np.meshgrid(eje_x, eje_y)
    clase, _n_clamped = asignar_clase(malla_x.ravel(), malla_y.ravel(), geometria)
    return {
        "x": eje_x.tolist(),
        "y": eje_y.tolist(),
        "z": np.asarray(clase, dtype=int).reshape(malla_x.shape).tolist(),
    }


def series_temporal_vanos(
    tabla: pd.DataFrame,
    *,
    circuito: str,
    fids: Iterable[str],
    n_ventanas: int,
) -> list[dict[str, Any]]:
    """One time series per vano in `fids`, in the order given: UITI and events
    across the `n_ventanas` windows of `circuito`.

    A window where the vano has no cell carries `None`, never `0`. A zero
    would read as "no UITI in that window", and what actually happened is
    that there was no measurement -- Plotly breaks the line at `None`, which
    is the honest mark for a gap.
    """
    circuitos = tabla["CIRCUITO"].astype(str).to_numpy()
    fids_tabla = tabla["FID_VANO"].astype(str).to_numpy()
    ventanas_i = tabla["ventana_i"].to_numpy()
    uiti = tabla["uiti_acumulado"].to_numpy()
    eventos = tabla["num_eventos"].to_numpy()

    del_circuito = circuitos == str(circuito)
    series: list[dict[str, Any]] = []
    for fid in fids:
        mask = del_circuito & (fids_tabla == str(fid))
        por_ventana = {int(v): (u, e) for v, u, e in
                       zip(ventanas_i[mask], uiti[mask], eventos[mask])}
        series.append(
            {
                "fid": str(fid),
                "x": list(range(int(n_ventanas))),
                "uiti": [float(por_ventana[i][0]) if i in por_ventana else None
                         for i in range(int(n_ventanas))],
                "eventos": [int(por_ventana[i][1]) if i in por_ventana else None
                            for i in range(int(n_ventanas))],
            }
        )
    return series


def reparto_por_clase(
    tabla: pd.DataFrame,
    clase_por_fila: np.ndarray,
    *,
    mask_ventana: np.ndarray,
    marcados: Iterable[str],
) -> list[dict[str, list]]:
    """UITI and event counts per class, over the MARKED vanos of the active
    window -- four entries, index 0-3.

    No marked vanos means four EMPTY groups, deliberately: this is 01.4's own
    rule for its violins, and its reason carries over unchanged -- a
    distribution over thousands of vanos and one over three draw identically,
    and nothing in a violin tells them apart. Falling back to the whole
    circuit here would silently change the subject of the panel.
    """
    marcados = {str(m) for m in marcados}
    grupos: list[dict[str, list]] = [{"uiti": [], "eventos": []} for _ in range(4)]
    if not marcados:
        return grupos

    mask = np.asarray(mask_ventana, dtype=bool) & np.isin(
        tabla["FID_VANO"].astype(str).to_numpy(), list(marcados)
    )
    clases = np.asarray(clase_por_fila)[mask]
    uiti = tabla["uiti_acumulado"].to_numpy()[mask]
    eventos = tabla["num_eventos"].to_numpy()[mask]
    for clase, u, e in zip(clases, uiti, eventos):
        grupos[int(clase)]["uiti"].append(float(u))
        grupos[int(clase)]["eventos"].append(int(e))
    return grupos


def nube_seleccion(
    tabla: pd.DataFrame,
    clase_por_fila: np.ndarray,
    *,
    mask_ventana: np.ndarray,
    marcados: Iterable[str] = (),
) -> dict[str, list]:
    """The highlighted points over `nube_fondo`: the cells of the marked
    vanos inside `mask_ventana` (a `construir_mask_cache` result, so the
    circuit+window filter is already cached). An EMPTY `marcados` highlights
    every vano of that circuit+window -- the same grain the simulated map and
    the relevance ranking fall back to, rather than an empty panel.

    A marked vano with no cell in the window contributes NO point: the row
    does not exist. Its signal is the black line on the map, never an
    invented point at the origin, which would read as "zero events, zero
    UITI" -- a measurement that was never taken.

    Returns column-parallel `x`/`y`/`clase`/`fid` lists; the caller maps
    `clase` to its colour (the palette lives in the notebook, next to the
    map's).
    """
    mask = np.asarray(mask_ventana, dtype=bool)
    fids = tabla["FID_VANO"].astype(str).to_numpy()
    marcados = {str(m) for m in marcados}
    if marcados:
        mask = mask & np.isin(fids, list(marcados))
    return {
        "x": tabla["num_eventos"].to_numpy()[mask].tolist(),
        "y": tabla["uiti_acumulado"].to_numpy()[mask].tolist(),
        "clase": np.asarray(clase_por_fila)[mask].astype(int).tolist(),
        "fid": fids[mask].tolist(),
    }


def _capa_vacia() -> dict[str, list]:
    return {"lat": [], "lon": [], "hovertext": [], "customdata": []}


def _densificar(
    lat: Sequence[float], lon: Sequence[float], paso: float
) -> tuple[list[float], list[float]]:
    """Interpolate vertices every `paso` degrees along a polyline.

    Scattermap resolves hover against a line's VERTICES, not against the line:
    plotly measures the cursor's distance to each point and drops anything
    beyond `hoverdistance`. MVLINSEC's tramos carry EXACTLY two vertices, so at
    working zoom the middle of a vano has none nearby -- no tooltip, and since
    plotly only turns a click into an event where there is hover, no way to
    mark the vano by touching it there either.
    """
    lat, lon = list(lat), list(lon)
    if len(lat) < 2 or paso <= 0:
        return lat, lon
    salida_lat, salida_lon = [lat[0]], [lon[0]]
    for i in range(1, len(lat)):
        d_lat, d_lon = lat[i] - lat[i - 1], lon[i] - lon[i - 1]
        cortes = max(1, min(_MAX_CORTES_TRAMO,
                            math.ceil(max(abs(d_lat), abs(d_lon)) / paso)))
        for j in range(1, cortes):
            salida_lat.append(round(lat[i - 1] + d_lat * j / cortes, 6))
            salida_lon.append(round(lon[i - 1] + d_lon * j / cortes, 6))
        salida_lat.append(lat[i])
        salida_lon.append(lon[i])
    return salida_lat, salida_lon


_MAX_CORTES_TRAMO = 600
"""Ceiling per segment, for the 12 km vano. Without it one outlier would
allocate tens of thousands of points on its own."""


def _agregar_tramo(
    capa: dict[str, list],
    fid: str,
    lat: Iterable[float],
    lon: Iterable[float],
    etiqueta: str,
    marca_extremos: float = 0.0,
    paso_densificado: float = 0.0,
    datos: Sequence[Any] | None = None,
) -> None:
    """Appends one vano's polyline plus its trailing `None` separator, keeping
    the four columns the same length. The separator carries the fid but an
    EMPTY label: it is a gap in the line, not a point with a tooltip.

    With `marca_extremos` > 0 it also appends 01's end-of-vano dash: two extra
    2-point horizontal segments, one centred on each end of the polyline,
    spanning `marca_extremos` degrees of longitude to either side. They go into
    the SAME layer -- not a marker and not a new trace -- because
    `marker.symbol` on Scattermap only accepts the map style's sprite icons,
    which hold no horizontal-line glyph, and a separate trace would need its own
    colour and width per class. Dash points carry the fid (so a click on one
    still resolves to its vano) but NO label: see the payload note below.
    """
    lat = list(lat)
    lon = list(lon)
    # `customdata` lleva SIEMPRE el fid primero -- es el canal que convierte un
    # clic en un vano -- y detras las columnas crudas que el `hovertemplate` de
    # la traza compone. Repetir ahi la etiqueta ya formateada costaba ~130
    # caracteres por punto; los datos crudos cuestan ~20 y permiten densificar.
    marca = [fid, *datos] if datos is not None else fid
    densa_lat, densa_lon = _densificar(lat, lon, paso_densificado)
    capa["lat"].extend([*densa_lat, None])
    capa["lon"].extend([*densa_lon, None])
    capa["hovertext"].extend([etiqueta] * len(densa_lat) + [""])
    capa["customdata"].extend([marca] * (len(densa_lat) + 1))
    if not marca_extremos or not lat:
        return
    # Etiqueta VACIA en los seis puntos del par de guiones. Medido sobre
    # MVLINSEC.shp: marcar los extremos lleva al peor circuito (DON23L13) de
    # 4.131 a 12.393 puntos por capa, y repetir ahi la etiqueta de ~130
    # caracteres suma ~1 MB a una sola rafaga del comm del widget -- por encima
    # del `iopub_data_rate_limit` de 1 MB/s de ipykernel, que descarta el
    # mensaje y deja la figura en blanco (mismo riesgo que documenta
    # `nube_fondo`). El vertice real del extremo queda en el centro del guion y
    # ya lleva la etiqueta, asi que el hover no pierde nada.
    for indice in (0, len(lat) - 1):
        capa["lat"].extend([lat[indice], lat[indice], None])
        capa["lon"].extend([
            round(lon[indice] - marca_extremos, 6),
            round(lon[indice] + marca_extremos, 6),
            None,
        ])
        capa["hovertext"].extend(["", "", ""])
        capa["customdata"].extend([marca] * 3)


TESELA_MAPLIBRE_PX = 512
"""Tile size MapLibre projects with. Verified against the browser, not assumed:
for DON23L13 at zoom 10.1553 the 512 model predicts a 328,9 x 389,9 px bounding
box and Chrome measured 329 x 390; the 256 model is off by exactly 2x."""


def _mercator_y(lat: float) -> float:
    """Normalised Web Mercator y in [0, 1]. A degree of latitude and one of
    longitude do NOT cover the same number of pixels, which is the whole reason
    the old span-in-degrees formula could not frame a circuit."""
    radianes = math.radians(lat)
    return (1 - math.log(math.tan(radianes) + 1 / math.cos(radianes)) / math.pi) / 2


def centro_y_zoom(
    bounds: Iterable[float] | None,
    *,
    ancho_px: float | None = None,
    alto_px: float | None = None,
    margen: float = 0.9,
) -> dict[str, Any] | None:
    """Center and zoom that frame one circuit's bounding box.

    With `ancho_px`/`alto_px` this is a real `fitBounds`: the zoom is whichever
    of the two constraints binds under Web Mercator, so the circuit fits ENTIRE
    inside the viewport and still fills the dimension that binds. `margen`
    leaves a border so the outermost vanos do not touch the edge.

    Without them it falls back to 01.4's original formula (zoom from the larger
    span in DEGREES, clamped to [9, 15]). That fallback exists because the
    caller does not always know the viewport: with `autosize` the width is the
    browser's to decide, and guessing it frames worse than the historical
    approximation.

    Measured, this is not cosmetic. Once 06's figure went full width its map
    became 1553 x 328 px, and the degrees formula put DON23L13 at 21% of the
    width and 119% of the HEIGHT -- centred, but clipped top and bottom, which
    reads as "it did not move to my circuit".

    Returns None when there are no bounds, so the caller leaves the current
    view untouched instead of centering on a made-up point.
    """
    bounds = list(bounds or ())
    if len(bounds) != 4:
        return None
    lat_min, lat_max, lon_min, lon_max = (float(v) for v in bounds)
    centro = {"lat": (lat_min + lat_max) / 2, "lon": (lon_min + lon_max) / 2}

    if (ancho_px and ancho_px > 0) or (alto_px and alto_px > 0):
        restricciones = []
        if ancho_px and ancho_px > 0:
            fraccion_x = max(abs(lon_max - lon_min) / 360.0, 1e-12)
            restricciones.append(float(ancho_px) * margen / (TESELA_MAPLIBRE_PX * fraccion_x))
        if alto_px and alto_px > 0:
            fraccion_y = max(abs(_mercator_y(lat_min) - _mercator_y(lat_max)), 1e-12)
            restricciones.append(float(alto_px) * margen / (TESELA_MAPLIBRE_PX * fraccion_y))
        # El zoom lo fija la dimension que se queda sin lugar primero. Con UNA sola
        # conocida se encuadra por esa: el widget del cuaderno sabe su alto exacto
        # (`height` x el dominio del subplot) pero no su ancho, que con `autosize` lo
        # decide el navegador. Encuadrar por el alto es lo que evita el recorte
        # vertical, que era el defecto; sobrar ancho solo deja mapa de mas a los lados.
        escala = min(restricciones)
        # Sin techo, un circuito de un solo vano pediria un zoom sin fin; sin
        # piso, uno que cruza el departamento se saldria de la region. El piso
        # baja de 9 a 3 a proposito: en un viewport apaisado y bajo, encuadrar
        # un circuito alto puede pedir menos de 9, y recortarlo era el defecto.
        return {"center": centro, "zoom": float(min(15.0, max(3.0, math.log2(escala))))}

    span = max(max(lat_max - lat_min, 1e-4), max(lon_max - lon_min, 1e-4))
    return {"center": centro, "zoom": float(min(15.0, max(9.0, np.log2(360.0 / span) - 0.4)))}


def fid_de_punto(customdata: Iterable[str] | None, point_inds: Iterable[int]) -> str | None:
    """Resolves a click to a vano through the trace's `customdata` column, the
    channel `capas_mapa_historico` fills. Returns None for an empty click or
    an index outside the column instead of guessing a neighbouring fid."""
    if customdata is None:
        return None
    columna = list(customdata)
    for indice in point_inds:
        if 0 <= int(indice) < len(columna):
            entrada = columna[int(indice)]
            # Con columnas extra cada entrada es una FILA y no un escalar; el
            # fid es siempre su primer elemento.
            if isinstance(entrada, (list, tuple)):
                return str(entrada[0]) if entrada else None
            return str(entrada)
    return None
