"""Guarda de retiro de los dos modulos que quedaron colgando del clasificador MGCECDL.

Se borraron el 2026-08-19, medidos sobre el arbol entero:

* `src/chec_impacto/interpretability/mgcecdl.py` (423 lineas) -- interpretabilidad de
  los flujos de CLASIFICACION del M-GCECDL, retirado en `2cf942b`. **No lo importaba
  nadie, ni una prueba**, y sus seis simbolos exportados no aparecian en un solo
  archivo del arbol. Sobrevivio al barrido anterior porque
  `docs/inventario-de-lo-suelto.md` lo listo como falso positivo por import perezoso
  (PEP 562): estar en `_ORIGEN` es ser ALCANZABLE, no ser usado.
* `src/chec_impacto/models/mgcecdl_graph_search.py` (283) y su prueba (322) -- la
  busqueda de hiperparametros del autocodificador de compuertas. Su unico consumidor
  era su propia prueba. Misma familia que los dos modulos retirados en agosto por el
  mismo motivo: una suite verde no distingue el codigo que funciona del que ademas
  hace falta.

**Y `optuna` sale con el.** El commit `6ba8c82` dejo escrita la condicion exacta --
*"es una herramienta de fuera de linea [...] si ese modulo se retira, optuna sale con
el"* -- porque `mgcecdl_graph_search.py` era su unico importador en todo el arbol. Esta
guarda es lo que impide que la dependencia vuelva por inercia.

Lo que NO se retira, y hay que no confundir: `chec_impacto.interpretability.mgcecdl_graph`
y `chec_impacto.models.mgcecdl_graph` estan muy vivos -- de ellos cuelgan `mgcecdl_mil`,
`mil_persistencia`, `mil_vano_ventana` y el simulador. Por eso esta guarda rastrea el
modulo con su frontera (`interpretability/mgcecdl.py`, no el prefijo `mgcecdl`) y los
seis simbolos por su nombre completo.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

BORRADOS = (
    "src/chec_impacto/interpretability/mgcecdl.py",
    "src/chec_impacto/models/mgcecdl_graph_search.py",
    "tests/test_mgcecdl_graph_search.py",
)

#: Los seis nombres que exportaba `interpretability/mgcecdl.py`, y que no tenian ni un
#: consumidor en todo el arbol el dia del borrado.
SIMBOLOS_RETIRADOS = (
    "build_classification_expected_class_outputs",
    "build_classification_modality_outputs_per_sample",
    "plot_classification_modality_expected_classes",
    "plot_classification_modality_radar",
    "summarize_classification_modality_support",
    "summarize_modality_reliability_by_class",
)

#: `mgcecdl_graph_search` se puede rastrear entero: ningun otro modulo lo contiene.
#: `interpretability/mgcecdl` NO, porque es prefijo de `mgcecdl_graph`, que sigue vivo.
PATRONES = (
    re.compile(r"mgcecdl_graph_search"),
    re.compile(r"interpretability[./]mgcecdl(?![_a-zA-Z])"),
    *(re.compile(rf"\b{re.escape(s)}\b") for s in SIMBOLOS_RETIRADOS),
)

RAICES_VIGILADAS = ("src", "tests", ".claude", "scripts", "aplicaciones", "notebooks",
                    "evals")
ARCHIVOS_VIGILADOS = ("README.md", "AGENTS.md", "requirements.txt")
SUFIJOS = {".py", ".md", ".json", ".yaml", ".yml", ".ipynb", ".txt"}
#: El REGISTRO HISTORICO del retiro, que nombra lo borrado para explicar por que ya no
#: esta. Misma excepcion que `docs/inventario-de-lo-suelto.md` en las guardas de retiro
#: anteriores: un archivo que cuenta el retiro no lo resucita. Los dos son de
#: requisitos, y que `optuna` no vuelva a DECLARARSE ahi lo vigila
#: `test_optuna_sale_con_su_unico_importador`, que mira lineas de dependencia y no prosa.
EXCEPCIONES = {
    Path(__file__).relative_to(RAIZ).as_posix(),
    "requirements.txt",
    "aplicaciones/databricks/simulador/requirements.txt",
}

#: Todo sitio del arbol que declara dependencias de Python.
REQUISITOS = (
    "requirements.txt",
    "aplicaciones/06_simulador/requirements.txt",
    "aplicaciones/databricks/simulador/requirements.txt",
    "aplicaciones/databricks/criticidad_chec/requirements.txt",
)


def _archivos() -> list[Path]:
    fuera: list[Path] = []
    for raiz in RAICES_VIGILADAS:
        base = RAIZ / raiz
        if not base.is_dir():
            continue
        for ruta in base.rglob("*"):
            if (ruta.is_file() and ruta.suffix in SUFIJOS
                    and "__pycache__" not in ruta.parts and ".venv" not in ruta.parts):
                fuera.append(ruta)
    for nombre in ARCHIVOS_VIGILADOS:
        if (RAIZ / nombre).is_file():
            fuera.append(RAIZ / nombre)
    return fuera


def test_los_tres_archivos_no_vuelven():
    for rel in BORRADOS:
        assert not (RAIZ / rel).exists(), (
            f"{rel} volvio al arbol. Era del clasificador MGCECDL, retirado en 2cf942b, "
            "y el dia del borrado no lo llamaba nadie.")


def test_nadie_los_nombra_en_codigo_ni_en_contratos():
    culpables: list[str] = []
    for ruta in _archivos():
        rel = ruta.relative_to(RAIZ).as_posix()
        if rel in EXCEPCIONES:
            continue
        texto = ruta.read_text(encoding="utf-8", errors="ignore")
        lineas = [f"  linea {i}: {linea.strip()[:120]}"
                  for i, linea in enumerate(texto.splitlines(), start=1)
                  if any(p.search(linea) for p in PATRONES)]
        if lineas:
            culpables.append(f"{rel}:\n" + "\n".join(lineas))
    assert not culpables, (
        "algo sigue nombrando lo retirado:\n" + "\n".join(culpables)
        + "\n\nUna mencion en prosa basta para que el proximo barrido lo de por vivo: "
          "fue exactamente lo que paso con estos dos en el inventario anterior.")


def test_el_grafo_vivo_no_se_fue_con_ellos():
    """`mgcecdl_graph` es OTRO modulo, y de el cuelga todo el camino MIL."""
    for rel in ("src/chec_impacto/interpretability/mgcecdl_graph.py",
                "src/chec_impacto/models/mgcecdl_graph.py",
                "src/chec_impacto/models/mgcecdl_mil.py"):
        assert (RAIZ / rel).exists(), f"{rel} no deberia haberse tocado"


def test_optuna_sale_con_su_unico_importador():
    """La condicion la dejo escrita el commit 6ba8c82: era su unico consumidor."""
    declarado = [r for r in REQUISITOS
                 if (RAIZ / r).is_file()
                 and re.search(r"(?m)^\s*optuna\b", (RAIZ / r).read_text(encoding="utf-8"))]
    assert not declarado, (
        f"optuna sigue declarado en {declarado} y ya no lo importa nadie en el arbol. "
        "El unico importador era `mgcecdl_graph_search.py`.")


def test_ningun_modulo_del_arbol_importa_optuna():
    importadores: list[str] = []
    for raiz in ("src", "scripts", "tests", "aplicaciones", "evals"):
        base = RAIZ / raiz
        if not base.is_dir():
            continue
        for ruta in base.rglob("*.py"):
            if "__pycache__" in ruta.parts or ".venv" in ruta.parts:
                continue
            if re.search(r"(?m)^\s*(?:import optuna|from optuna\b)",
                         ruta.read_text(encoding="utf-8", errors="ignore")):
                importadores.append(ruta.relative_to(RAIZ).as_posix())
    assert not importadores, f"optuna volvio a tener importadores: {importadores}"
