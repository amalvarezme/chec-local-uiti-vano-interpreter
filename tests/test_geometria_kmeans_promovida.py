"""D3's three gating equality checks for promoting the KMeans geometry from a
notebook-04-extracted cache to a tracked repository artifact
(`data/geometria_kmeans_014_v1.json`).

Design D3 rejected re-serializing the `.pt`'s floats into JSON (float repr
round-trip could move `GEOMETRIAS_SHA1_ESPERADO` for no semantic reason) and
rejected reading the geometry from the `.pt` at runtime (`torch.load`
materializes the whole state_dict, landing torch on every lightweight
consumer). Instead: commit today's extraction bytes verbatim, and use
`data/models/mil_vano_ventana_v1.pt` as an INDEPENDENT WITNESS that those
bytes are correct -- never as the runtime source.

All three checks must pass; a failure here means the promotion must not
proceed (per spec's "GIVEN the migration has completed this step" gate for
this domain).

See:
  - spec: `sdd/retire-base-apps-notebooks/spec` (domain criticidad-geometria)
  - design: `sdd/retire-base-apps-notebooks/design` (D3)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from chec_impacto.models.criticality_assignment import (
    CLAVE_ESPACIO_CANONICO,
    GEOMETRIAS_SHA1_ESPERADO,
    asignar_clase,
    cargar_geometria_014,
    verificar_sha1_geometrias,
)
from chec_impacto.models.mil_persistencia import cargar_modelo_mil

REPO_ROOT = Path(__file__).resolve().parents[1]
RUTA_GEOMETRIA_PROMOVIDA = REPO_ROOT / "data" / "geometria_kmeans_014_v1.json"
RUTA_ARTEFACTO_MIL = REPO_ROOT / "data" / "models" / "mil_vano_ventana_v1.pt"

pytestmark = pytest.mark.skipif(
    not RUTA_ARTEFACTO_MIL.exists(),
    reason="data/models/mil_vano_ventana_v1.pt no esta presente en este checkout.",
)


def test_geometria_promovida_existe_y_es_cargable():
    assert RUTA_GEOMETRIA_PROMOVIDA.exists(), (
        "data/geometria_kmeans_014_v1.json debe existir como artefacto versionado "
        "-- es la fuente que reemplaza la extraccion de la notebook 04."
    )
    geometria = cargar_geometria_014(RUTA_GEOMETRIA_PROMOVIDA, clave=CLAVE_ESPACIO_CANONICO)
    assert geometria.centroides.shape == (4, 2)


# --- Check 1: field-by-field equality against the .pt's own geometry -------


def test_check_1_geometria_promovida_coincide_campo_a_campo_con_el_pt():
    predictor = cargar_modelo_mil(RUTA_ARTEFACTO_MIL)
    geometria_pt = predictor.geometria
    geometria_json = cargar_geometria_014(RUTA_GEOMETRIA_PROMOVIDA, clave=CLAVE_ESPACIO_CANONICO)

    assert geometria_pt.logs == geometria_json.logs
    np.testing.assert_array_equal(geometria_pt.offset, geometria_json.offset)
    np.testing.assert_array_equal(geometria_pt.scale, geometria_json.scale)
    np.testing.assert_array_equal(geometria_pt.centroides, geometria_json.centroides)


# --- Check 2: label equality over real (n_obs, u) pairs ---------------------


def test_check_2_asignar_clase_produce_las_mismas_etiquetas_desde_las_dos_fuentes():
    predictor = cargar_modelo_mil(RUTA_ARTEFACTO_MIL)
    geometria_pt = predictor.geometria
    geometria_json = cargar_geometria_014(RUTA_GEOMETRIA_PROMOVIDA, clave=CLAVE_ESPACIO_CANONICO)

    # A spread of real-shaped (n_obs, u) pairs, not just the four exact
    # centroids -- triangulates beyond the trivial "distance to itself is
    # zero" case that landing exactly on a centroid would produce.
    n_obs = np.array([1.0, 2.0, 5.0, 12.0, 30.0, 45.0])
    u = np.array([0.5, 3.0, 25.0, 90.0, 300.0, 900.0])

    clase_pt, n_clamped_pt = asignar_clase(n_obs, u, geometria_pt)
    clase_json, n_clamped_json = asignar_clase(n_obs, u, geometria_json)

    np.testing.assert_array_equal(clase_pt, clase_json)
    assert n_clamped_pt == n_clamped_json


# --- Check 3: sha1 pin equality ---------------------------------------------


def test_check_3_sha1_de_la_geometria_promovida_coincide_con_el_pin():
    sha1_real, coincide = verificar_sha1_geometrias(
        RUTA_GEOMETRIA_PROMOVIDA, esperado=GEOMETRIAS_SHA1_ESPERADO
    )
    assert coincide is True
    assert sha1_real == GEOMETRIAS_SHA1_ESPERADO
