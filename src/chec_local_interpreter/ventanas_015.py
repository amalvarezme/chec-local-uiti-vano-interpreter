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

from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

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
        _agregar_tramo(capas.get(clase, sin_dato), fid, lat, lon, etiqueta)
        if fid in marcados:
            _agregar_tramo(marcados_capa, fid, lat, lon, etiqueta)
            _agregar_tramo(
                marcados_por_clase.get(clase, marcados_sin_dato), fid, lat, lon, etiqueta
            )

    return {
        "clases": capas,
        "sin_dato": sin_dato,
        "marcados": marcados_capa,
        "marcados_por_clase": marcados_por_clase,
        "marcados_sin_dato": marcados_sin_dato,
    }


def nube_fondo(
    tabla: pd.DataFrame, clase_por_fila: np.ndarray
) -> list[dict[str, list[float]]]:
    """01.4's KMeans cloud background (its row-1 col-3 panel): EVERY
    (vano, ventana) cell of `tabla` as a point `(num_eventos,
    uiti_acumulado)`, grouped into the 4 class layers by `clase_por_fila`
    (one class per row of `tabla`, in row order).

    It never depends on the selection: 01.4 fits KMeans once over all cells,
    so choosing a circuit or marking vanos only changes what is highlighted,
    never where the boundaries fall. Computing it once and only restyling the
    highlight is what keeps the panel free at interaction time.
    """
    clase_por_fila = np.asarray(clase_por_fila)
    x = tabla["num_eventos"].to_numpy()
    y = tabla["uiti_acumulado"].to_numpy()
    capas = []
    for clase in range(4):
        mask = clase_por_fila == clase
        capas.append({"x": x[mask].tolist(), "y": y[mask].tolist()})
    return capas


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


def _agregar_tramo(
    capa: dict[str, list], fid: str, lat: Iterable[float], lon: Iterable[float], etiqueta: str
) -> None:
    """Appends one vano's polyline plus its trailing `None` separator, keeping
    the four columns the same length. The separator carries the fid but an
    EMPTY label: it is a gap in the line, not a point with a tooltip."""
    lat = list(lat)
    capa["lat"].extend([*lat, None])
    capa["lon"].extend([*lon, None])
    capa["hovertext"].extend([etiqueta] * len(lat) + [""])
    capa["customdata"].extend([fid] * (len(lat) + 1))


def centro_y_zoom(bounds: Iterable[float] | None) -> dict[str, Any] | None:
    """01.4's own framing formula (cell 7, `map.center` / `map.zoom`), ported
    verbatim: center on the middle of the circuit's bounding box and derive
    the zoom from its LARGER span, clamped to [9, 15]. Without the clamp a
    one-vano circuit would zoom past any tile level, and a circuit spanning
    half the department would zoom out of the region entirely.

    Returns None when there are no bounds, so the caller leaves the current
    view untouched instead of centering on a made-up point.
    """
    bounds = list(bounds or ())
    if len(bounds) != 4:
        return None
    lat_min, lat_max, lon_min, lon_max = (float(v) for v in bounds)
    span = max(max(lat_max - lat_min, 1e-4), max(lon_max - lon_min, 1e-4))
    zoom = min(15.0, max(9.0, np.log2(360.0 / span) - 0.4))
    return {
        "center": {"lat": (lat_min + lat_max) / 2, "lon": (lon_min + lon_max) / 2},
        "zoom": float(zoom),
    }


def fid_de_punto(customdata: Iterable[str] | None, point_inds: Iterable[int]) -> str | None:
    """Resolves a click to a vano through the trace's `customdata` column, the
    channel `capas_mapa_historico` fills. Returns None for an empty click or
    an index outside the column instead of guessing a neighbouring fid."""
    if customdata is None:
        return None
    columna = list(customdata)
    for indice in point_inds:
        if 0 <= int(indice) < len(columna):
            return str(columna[int(indice)])
    return None
