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
        return dict(zip(fids[mask].tolist(), clase.tolist()))

    return clases_para


def capas_mapa_historico(
    geo_circuito: Mapping[str, Any],
    clases_por_fid: Mapping[str, int],
    *,
    marcados: Iterable[str] = (),
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
    """
    capas: dict[int, dict[str, list]] = {clase: {"lat": [], "lon": []} for clase in range(4)}
    sin_dato: dict[str, list] = {"lat": [], "lon": []}
    marcados_capa: dict[str, list] = {"lat": [], "lon": []}
    marcados = set(marcados)

    for fid, lat, lon in zip(geo_circuito["fids"], geo_circuito["lat"], geo_circuito["lon"]):
        destino = capas.get(clases_por_fid.get(fid), sin_dato)
        destino["lat"].extend([*lat, None])
        destino["lon"].extend([*lon, None])
        if fid in marcados:
            marcados_capa["lat"].extend([*lat, None])
            marcados_capa["lon"].extend([*lon, None])

    return {"clases": capas, "sin_dato": sin_dato, "marcados": marcados_capa}
