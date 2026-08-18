"""Guarda de retiro de `chec_local_interpreter.graph_view_builder`.

El modulo existia SOLO para el paso 2.5 de `/informe-gerencial` -- el rebuild
aislado de graphify mas la mineria de temas recurrentes que alimentaba la seccion
"Patrones cross-circuito (grafo)". Esa seccion se retiro el 2026-08-18, el paso
se fue con ella, y el modulo quedo sin un solo llamador en produccion: su propio
`SKILL.md` lo describia como "dead code pending a decision".

Se borro el 2026-08-18. El grafo que el informe SI dibuja hoy es otro,
`intervention_graph.py`, que lee los artefactos de corrida de los agentes y
no toca graphify en ningun momento.

**Por que una guarda y no solo el borrado.** El modulo sobrevivio a un barrido
previo de codigo muerto por una sola razon: `README.md` seguia describiendo el
paso 2.5 como vivo, y el analizador perdona a todo modulo citado en prosa. La
documentacion obsoleta mantiene vivo al codigo muerto. Esta prueba corta las dos
puntas a la vez -- el archivo no vuelve, y la prosa que lo resucitaria tampoco.

Mismo estilo que `tests/test_docs_llm_directory_references_removed.py`: rastreo
literal de la cadena exacta, sobre una lista explicita de sitios.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODULO_RETIRADO = "src/chec_local_interpreter/graph_view_builder.py"
PRUEBA_RETIRADA = "tests/test_graph_view_builder.py"

#: La cadena que delata una resurreccion, sea import, ruta o mencion en un diagrama.
NOMBRE_RETIRADO = "graph_view_builder"

#: Arboles donde una mencion significa que algo lo volvio a invocar o a documentar
#: como vivo. `docs/inventario-de-lo-suelto.md` queda FUERA a proposito: es el
#: registro historico del retiro y lo nombra para explicarlo, no para invocarlo.
RAICES_VIGILADAS = (
    "src",
    "tests",
    ".claude",
    "scripts",
    "aplicaciones",
)

ARCHIVOS_VIGILADOS = ("README.md", "AGENTS.md")

#: Este mismo archivo nombra el modulo en cada linea; excluirlo no debilita nada.
EXCEPCIONES = {Path(__file__).relative_to(PROJECT_ROOT).as_posix()}

#: Citar a ESTA guarda por su nombre de archivo no resucita nada, y los contratos
#: que documentan sus pruebas tienen que poder nombrarla.
NOMBRE_DE_LA_GUARDA = Path(__file__).stem

SUFIJOS = {".py", ".md", ".json", ".yaml", ".yml", ".ipynb"}


def _archivos_a_revisar() -> list[Path]:
    encontrados: list[Path] = []
    for raiz in RAICES_VIGILADAS:
        base = PROJECT_ROOT / raiz
        if not base.is_dir():
            continue
        for ruta in base.rglob("*"):
            if not ruta.is_file() or ruta.suffix not in SUFIJOS:
                continue
            if "__pycache__" in ruta.parts:
                continue
            encontrados.append(ruta)
    for nombre in ARCHIVOS_VIGILADOS:
        ruta = PROJECT_ROOT / nombre
        if ruta.is_file():
            encontrados.append(ruta)
    return encontrados


def test_el_modulo_y_su_prueba_no_vuelven():
    for rel in (MODULO_RETIRADO, PRUEBA_RETIRADA):
        assert not (PROJECT_ROOT / rel).exists(), (
            f"{rel} volvio al arbol. Existia solo para el paso 2.5 de "
            "/informe-gerencial, que se retiro: el grafo que el informe dibuja hoy "
            "lo construye intervention_graph.py desde los artefactos de corrida."
        )


def test_nadie_lo_nombra_en_codigo_ni_en_contratos():
    culpables: list[str] = []
    for ruta in _archivos_a_revisar():
        rel = ruta.relative_to(PROJECT_ROOT).as_posix()
        if rel in EXCEPCIONES:
            continue
        texto = ruta.read_text(encoding="utf-8", errors="ignore")
        if NOMBRE_RETIRADO not in texto:
            continue
        lineas = [
            f"  linea {i}: {linea.strip()}"
            for i, linea in enumerate(texto.splitlines(), start=1)
            if NOMBRE_RETIRADO in linea and NOMBRE_DE_LA_GUARDA not in linea
        ]
        if not lineas:
            continue
        culpables.append(f"{rel}:\n" + "\n".join(lineas))

    assert not culpables, (
        "`graph_view_builder` sigue nombrado fuera del registro historico:\n"
        + "\n".join(culpables)
        + "\n\nUna mencion en prosa basta para que el proximo barrido de codigo "
        "muerto lo de por vivo: fue exactamente lo que paso con README.md."
    )
