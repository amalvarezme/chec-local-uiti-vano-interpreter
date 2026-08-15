"""Geometry PRODUCER for the tracked KMeans artifact
`data/geometria_kmeans_014_v1.json` (design D3, `sdd/retire-base-apps-notebooks`).

## Why this exists

Notebook 04 used to be the only source of the canonical KMeans geometry:
`scripts/extract_geometrias_014.py` (retired) parsed it out of the
notebook's committed cell-7 output. `data/geometria_kmeans_014_v1.json`
replaced that lazy extraction with a committed artifact -- but a committed
artifact with no producer is unreproducible the day notebook 04 is deleted.
This script IS that producer.

It reuses `chec_local_interpreter.ventanas_015.construir_ventanas` and
`construir_tabla_vano_ventana` (already tested, byte-for-byte reproductions
of notebook 04's own cells 2/3 -- see their docstrings), and replicates
notebook 04 cell 4's `geometria()` fit verbatim: KMeans over 4 groups, in
the FIXED space (eje x lineal, eje y `log10`, escalador `minmax`),
`random_state=42`, `n_init=10`. The four resulting groups are sorted
ascending by each raw group's median `uiti_acumulado`, so the exported
centroid index k IS the final class id (0=Bajo .. 3=Alto) -- no remapping
happens downstream.

## Non-goal

This does NOT retrain `data/models/mil_vano_ventana_v1.pt`. It refits the
much smaller, unrelated KMeans geometry only -- see
`sdd/retire-base-apps-notebooks/spec`'s Non-Goals section.

## Verified reproduction

Running this script against the real, committed `Indicadores_vano_v3.csv`
reproduces `data/geometria_kmeans_014_v1.json`'s `geometrias` block (and
therefore its `geometrias_sha1`, and therefore
`GEOMETRIAS_SHA1_ESPERADO`) byte-identical -- see
`tests/test_exportar_geometria.py`.

See:
  - spec: `sdd/retire-base-apps-notebooks/spec` (domain criticidad-geometria)
  - design: `sdd/retire-base-apps-notebooks/design` (D3)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.csv as pacsv
from sklearn.cluster import KMeans
from sklearn.preprocessing import MinMaxScaler

REPO_ROOT = Path(__file__).resolve().parents[1]
RUTA_CSV_DEFECTO = REPO_ROOT / "data" / "Indicadores_vano_v3.csv"
RUTA_SALIDA_DEFECTO = REPO_ROOT / "data" / "geometria_kmeans_014_v1.json"

# Mismos valores que notebook 04's cell 2 / `criticality_assignment.py`.
CLAVE_ESPACIO = "0"
SEMILLA = 42
GRUPOS = ["Bajo", "Medio", "Medio-Alto", "Alto"]
COLUMNAS_BASE = ("CIRCUITO", "FID_VANO", "UITI_VANO", "FECHA")


def _normalizar_fid(serie: pd.Series) -> pd.Series:
    """Mismo normalizador que notebook 04's `_norm_id` / `ventanas_015`."""
    return (
        serie.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .replace({"": pd.NA, "<NA>": pd.NA, "nan": pd.NA, "None": pd.NA})
    )


def leer_eventos(ruta_csv: str | Path = RUTA_CSV_DEFECTO, columnas=COLUMNAS_BASE) -> pd.DataFrame:
    """Mismo lector incremental de pyarrow que notebook 04's `leer_eventos`
    (y el 03): el CSV completo trae ~270 columnas y solo se usan cuatro."""
    lector = pacsv.open_csv(
        str(ruta_csv),
        convert_options=pacsv.ConvertOptions(include_columns=list(columnas)),
    )
    df = lector.read_all().to_pandas()
    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce")
    df["UITI_VANO"] = pd.to_numeric(df["UITI_VANO"], errors="coerce").fillna(0.0)
    df["FID_VANO"] = _normalizar_fid(df["FID_VANO"])
    return df


def ajustar_geometria(tabla: pd.DataFrame) -> tuple[dict, int]:
    """Notebook 04 cell 4's `geometria(log_x=False, log_y=True, prep='minmax')`,
    reproduced verbatim: fits KMeans(4) ONCE over ALL vano x ventana cells in
    the fixed space. Returns the geometry block (`logs`/`offset`/`scale`/
    `centroides`) and the count of points whose nearest-centroid label
    (recomputed from the rounded, exported geometry) disagrees with
    `KMeans.predict` -- a rounding-tolerance sanity check, not a fit metric.
    """
    xy = tabla[["num_eventos", "uiti_acumulado"]].to_numpy(dtype=float)
    x = xy.copy()
    x[:, 1] = np.log10(x[:, 1])

    escalador = MinMaxScaler().fit(x)
    modelo = KMeans(n_clusters=4, random_state=SEMILLA, n_init=10).fit(escalador.transform(x))

    offset, escala = np.round(escalador.data_min_, 6), np.round(escalador.data_range_, 6)
    centroides = np.round(modelo.cluster_centers_, 6)

    z = (x - offset) / escala
    cruda = (((z[:, None, :] - centroides[None, :, :]) ** 2).sum(axis=2)).argmin(axis=1)
    difieren = int((cruda != modelo.predict(escalador.transform(x))).sum())
    assert difieren <= max(5, int(0.001 * len(cruda))), (
        f"{difieren} de {len(cruda)} no coinciden con predict(): no es un empate de "
        "frontera por redondeo -- revisa el fit antes de continuar."
    )

    orden = list(np.argsort([np.median(xy[cruda == c, 1]) for c in range(4)]))
    return {
        "logs": [False, True],
        "offset": offset.tolist(),
        "scale": escala.tolist(),
        "centroides": centroides[orden].tolist(),
    }, difieren


def _sha1_de_geometrias(geometrias: dict) -> str:
    """Misma canonicalizacion que usaba el `extract_geometrias_014.py`
    retirado: sha1 sobre el bloque `geometrias` con llaves ordenadas y sin
    espacios."""
    canonical = json.dumps(geometrias, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def exportar_geometria(
    ruta_csv: str | Path = RUTA_CSV_DEFECTO,
    ruta_salida: str | Path = RUTA_SALIDA_DEFECTO,
) -> Path:
    """Refits the canonical KMeans geometry from `ruta_csv` and writes the
    `{"grupos", "geometrias", "geometrias_sha1"}` payload to `ruta_salida`.

    Uses `ventanas_015.construir_ventanas`/`construir_tabla_vano_ventana` for
    the window cut list and per-(vano, ventana) aggregation -- imported
    lazily so this script stays importable even in environments without
    torch (`chec_local_interpreter.ventanas_015` pulls it in transitively).
    """
    from chec_local_interpreter.ventanas_015 import (
        construir_tabla_vano_ventana,
        construir_ventanas,
    )

    ruta_csv = Path(ruta_csv)
    ruta_salida = Path(ruta_salida)

    df = leer_eventos(ruta_csv)
    ventanas = construir_ventanas(df["FECHA"])
    tabla = construir_tabla_vano_ventana(df, ventanas)

    geometria_bloque, _difieren = ajustar_geometria(tabla)
    geometrias = {CLAVE_ESPACIO: geometria_bloque}

    payload = {
        "grupos": GRUPOS,
        "geometrias": geometrias,
        "geometrias_sha1": _sha1_de_geometrias(geometrias),
    }

    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(json.dumps(payload), encoding="utf-8")
    return ruta_salida


def main() -> None:
    ruta = exportar_geometria()
    print(f"Geometria KMeans exportada en: {ruta}")


if __name__ == "__main__":
    main()
