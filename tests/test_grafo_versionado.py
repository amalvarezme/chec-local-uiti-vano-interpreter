"""Que del grafo de graphify viaja a GitHub, y que se queda en esta maquina.

`graphify-out/` estuvo entero en `.gitignore`, y para casi todo estaba bien: el grafo se
reconstruye con `graphify update .` en unos segundos. Casi.

**La mitad cara no se reconstruye barata.** La extraccion semantica de los documentos,
PDF e imagenes la hace un LLM, y costo del orden de 1.000.000 de tokens. Vive en
`cache/` y pesa 2,6 MB. Un clon en otra maquina -- que es como se despliega este
proyecto -- la pagaria otra vez, o se quedaria con un grafo que solo entiende el codigo.

Lo que se versiona y lo que no sale de dos medidas, no de una preferencia:

* `graph.json` pesa 11 MB y **comprime a 0,8 MB** (14:1: es JSON con las mismas claves
  repetidas). Por eso va por git normal y no por LFS -- LFS le cobraria cuota a un
  archivo que el pack resuelve solo.
* el cache de AST pesa 12 MB, se rehace en 30 s y cambia ENTERO con cada version del
  paquete. Versionarlo seria pagar el 80% del peso por el 0% del valor.

Y dos archivos no pueden viajar aunque son pequenos: `.graphify_python` y
`.graphify_root` guardan rutas absolutas de la maquina que corrio graphify.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _rastreados() -> set[str]:
    salida = subprocess.run(["git", "ls-files", "graphify-out"], cwd=RAIZ,
                            capture_output=True, text=True, check=True)
    return set(salida.stdout.split())


RASTREADOS = _rastreados()

#: Lo que un clon necesita para tener el grafo sin reconstruir nada.
IMPRESCINDIBLES = (
    "graphify-out/graph.json",
    "graphify-out/GRAPH_REPORT.md",
    "graphify-out/graph.html",
    "graphify-out/manifest.json",
)


@pytest.mark.parametrize("ruta", IMPRESCINDIBLES)
def test_lo_que_el_clon_necesita_esta_rastreado(ruta: str):
    assert ruta in RASTREADOS, (
        f"{ruta} no viaja al repositorio. Un clon nuevo se quedaria sin grafo hasta "
        "reconstruirlo, y la mitad semantica no se reconstruye sin volver a gastar el "
        "millon de tokens.")


def test_la_extraccion_semantica_viaja():
    """Es la unica parte que un `graphify update .` NO puede rehacer."""
    semanticos = [r for r in RASTREADOS
                  if r.startswith("graphify-out/cache/") and "/ast/" not in r]
    assert len(semanticos) >= 30, (
        f"solo {len(semanticos)} archivos de cache semantico rastreados; se esperaban "
        "decenas. Sin ellos el clon reextrae documentos, PDF e imagenes con un LLM.")


def test_el_cache_de_ast_no_viaja():
    """12 MB que `graphify update .` rehace en 30 s, y que cambian con cada version."""
    intrusos = [r for r in RASTREADOS if r.startswith("graphify-out/cache/ast/")]
    assert not intrusos, (
        f"{len(intrusos)} archivos del cache de AST se colaron al repositorio")


def test_los_respaldos_fechados_no_viajan():
    """graphify escribe uno antes de cada reconstruccion; son copias del mismo grafo."""
    import re
    patron = re.compile(r"^graphify-out/\d{4}-\d{2}-\d{2}/")
    intrusos = [r for r in RASTREADOS if patron.match(r)]
    assert not intrusos, f"respaldos fechados rastreados: {intrusos[:4]}"


@pytest.mark.parametrize("ruta", ("graphify-out/.graphify_python",
                                  "graphify-out/.graphify_root"))
def test_las_rutas_de_esta_maquina_no_viajan(ruta: str):
    assert ruta not in RASTREADOS, (
        f"{ruta} guarda una ruta absoluta de la maquina que corrio graphify: en otro "
        "clon no significa nada, y de paso publica el directorio personal.")


def test_el_grafo_no_entra_por_lfs():
    """Comprime 14:1; LFS le cobraria cuota a lo que el pack resuelve gratis."""
    atributos = (RAIZ / ".gitattributes").read_text(encoding="utf-8")
    assert "graphify-out" not in atributos, (
        "graphify-out entro en .gitattributes: `graph.json` comprime a 0,8 MB y no "
        "necesita LFS, que ademas ya carga con el CSV, el joblib y los shapefiles.")
