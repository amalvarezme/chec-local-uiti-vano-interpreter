"""RED/GREEN test for `scripts/exportar_geometria.py` -- the geometry
PRODUCER (design D3, task 0.13).

Once notebook 04 is eventually deleted (a later slice), the tracked
`data/geometria_kmeans_014_v1.json` artifact would be unreproducible without
a producer that re-fits the same KMeans geometry from raw data. This script
IS that producer: it reuses `ventanas_015.construir_ventanas`/
`construir_tabla_vano_ventana` (already tested, byte-for-byte reproductions
of notebook 04's own cells 2/3) and replicates notebook 04 cell 4's KMeans
fit verbatim (4 groups, fixed space: eje x lineal, eje y log10, escalador
minmax, `random_state=42`, `n_init=10`).

Non-goal: this does NOT retrain `data/models/mil_vano_ventana_v1.pt` -- see
`sdd/retire-base-apps-notebooks/spec`'s Non-Goals section.

See:
  - spec: `sdd/retire-base-apps-notebooks/spec` (domain criticidad-geometria)
  - design: `sdd/retire-base-apps-notebooks/design` (D3)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUTA_CSV = REPO_ROOT / "data" / "Indicadores_vano_v3.csv"
RUTA_GEOMETRIA_PROMOVIDA = REPO_ROOT / "data" / "geometria_kmeans_014_v1.json"

pytestmark = pytest.mark.skipif(
    not RUTA_CSV.exists() or RUTA_CSV.stat().st_size < 1024 * 1024,
    reason="data/Indicadores_vano_v3.csv no esta presente (o es un puntero de Git LFS).",
)


def test_exportar_geometria_reproduce_el_artefacto_comprometido_byte_a_byte(tmp_path):
    from scripts.exportar_geometria import exportar_geometria

    destino = tmp_path / "geometria_kmeans_014_v1.json"
    ruta_escrita = exportar_geometria(RUTA_CSV, destino)

    assert ruta_escrita == destino
    assert destino.exists()

    producido = json.loads(destino.read_text(encoding="utf-8"))
    comprometido = json.loads(RUTA_GEOMETRIA_PROMOVIDA.read_text(encoding="utf-8"))

    # The `geometrias` block is the part the sha1 pin covers and the part
    # `asignar_clase` actually reads -- this is the byte-identical
    # requirement task 0.14 names.
    assert producido["geometrias"] == comprometido["geometrias"]
    assert producido["grupos"] == comprometido["grupos"]
    assert producido["geometrias_sha1"] == comprometido["geometrias_sha1"]


def test_exportar_geometria_produce_un_sha1_que_coincide_con_el_pin(tmp_path):
    from chec_impacto.models.criticality_assignment import GEOMETRIAS_SHA1_ESPERADO
    from scripts.exportar_geometria import exportar_geometria

    destino = tmp_path / "geometria_kmeans_014_v1.json"
    exportar_geometria(RUTA_CSV, destino)

    producido = json.loads(destino.read_text(encoding="utf-8"))
    assert producido["geometrias_sha1"] == GEOMETRIAS_SHA1_ESPERADO
