"""Historical vano criticality classes, reused from 01.4's KMeans geometry
(notebook 01.5, PR1).

01.5's row-1 (historical) classes are NEVER re-fit here. This module
composes the same read-only chain notebook 10 already uses --
`extraer_geometrias_014` -> `verificar_sha1_geometrias` ->
`cargar_geometria_014` -> `asignar_clase` -- so 01.4's own nearest-centroid
KMeans assignment is replayed exactly, and a future edit to 01.4 that moves
the centroids fails loudly instead of silently drifting downstream classes.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-explainability-panel`, requirement "Geometry reuse via
    sha1-guarded 01.4 extractor")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section F, "01.4 geometry reuse and its failure modes")
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

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
