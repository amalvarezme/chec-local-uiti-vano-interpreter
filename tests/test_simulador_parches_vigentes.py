"""Las marcas que `preparar.py` busca en el cuaderno 06 siguen existiendo.

## Por que existe esta prueba

`aplicaciones/06_simulador/preparar.py` construye el paquete del simulador
parcheando una copia del cuaderno 06 por CONTENIDO: busca un texto literal y lo
reemplaza, exigiendo que aparezca exactamente una vez. Es un buen diseno --- un
parche que no encuentra su sitio detiene la construccion en vez de producir un
cuaderno que muere dentro del servidor.

El problema es CUANDO se entera. Esa comprobacion solo corre al construir el
paquete, y construir exige el CSV de 566 MB y el modelo entrenado, asi que
ninguna prueba automatica la ejercita. Medido: al promover la geometria KMeans a
un artefacto versionado y borrar `scripts/extract_geometrias_014.py`, el cuaderno
06 quedo con un import de un modulo inexistente y `pytest -q` siguio en verde ---
2.310 pruebas que no miran esa ruta.

Esta prueba cierra ese hueco sin construir nada: compara las marcas que
`preparar.py` declara contra el texto del cuaderno, que es exactamente la
condicion que la construccion verificaria mas tarde y mas caro.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PREPARAR = RAIZ / "aplicaciones" / "06_simulador" / "preparar.py"
CUADERNO_06 = RAIZ / "notebooks" / "base_apps" / "06_uiti_vano_explicabilidad_simulador.ipynb"

# Los argumentos de cada ayudante que son MARCAS a buscar, no texto de reemplazo.
# `_reemplazar(fuente, viejo, nuevo, *, etiqueta)`         -> se busca `viejo`
# `_reemplazar_rango(fuente, desde, hasta, nuevo, *, ...)` -> se buscan `desde` y `hasta`
POSICIONES_DE_MARCA = {"_reemplazar": (1,), "_reemplazar_rango": (1, 2)}


def _fuente_del_cuaderno() -> str:
    """El texto de las celdas de codigo, tal como lo ve `preparar.py`."""
    cuaderno = json.loads(CUADERNO_06.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(celda["source"])
        for celda in cuaderno["cells"]
        if celda["cell_type"] == "code"
    )


def _marcas_declaradas() -> list[tuple[str, str]]:
    """`(etiqueta, marca)` por cada literal que `preparar.py` va a buscar.

    Se lee con `ast` y no con una expresion regular porque las llamadas son
    multilinea y algunas marcas llevan comillas dentro.
    """
    arbol = ast.parse(PREPARAR.read_text(encoding="utf-8"))
    marcas: list[tuple[str, str]] = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Name):
            continue
        posiciones = POSICIONES_DE_MARCA.get(nodo.func.id)
        if posiciones is None:
            continue
        etiqueta = next(
            (
                kw.value.value
                for kw in nodo.keywords
                if kw.arg == "etiqueta" and isinstance(kw.value, ast.Constant)
            ),
            f"linea {nodo.lineno}",
        )
        for posicion in posiciones:
            if posicion < len(nodo.args) and isinstance(nodo.args[posicion], ast.Constant):
                valor = nodo.args[posicion].value
                if isinstance(valor, str):
                    marcas.append((etiqueta, valor))
    return marcas


def test_preparar_declara_al_menos_una_marca():
    """Guarda de la propia prueba: si el extractor deja de encontrar marcas, las
    comprobaciones de abajo pasarian vacias y no dirian nada."""
    assert len(_marcas_declaradas()) >= 5


@pytest.mark.parametrize("etiqueta, marca", _marcas_declaradas())
def test_cada_marca_de_preparar_aparece_una_vez_en_el_cuaderno(etiqueta, marca):
    apariciones = _fuente_del_cuaderno().count(marca)
    assert apariciones == 1, (
        f"[{etiqueta}] la marca aparece {apariciones} veces en el cuaderno 06 y "
        f"deberia aparecer 1. `construir_paquete()` abortaria.\n"
        f"  buscaba: {marca.strip().splitlines()[0][:90]!r}"
    )


def test_el_cuaderno_06_no_importa_el_script_de_extraccion_borrado():
    """`scripts/extract_geometrias_014.py` ya no existe: la geometria KMeans viaja
    como artefacto versionado. Un import suelto aqui revienta la celda 1 entera.

    Se busca la SENTENCIA de import y no el nombre a secas: mencionarlo en un
    comentario que explica por que dejo de existir es legitimo, y una prueba que
    lo prohibiera empujaria a borrar la explicacion en vez del acoplamiento.
    """
    fuente = _fuente_del_cuaderno()
    sentencias = re.findall(
        r"^\s*(?:from\s+scripts\.extract_geometrias_014\b|import\s+scripts\.extract_geometrias_014\b)",
        fuente,
        re.M,
    )
    assert sentencias == [], sentencias


def test_el_cuaderno_06_lee_la_geometria_del_artefacto_versionado():
    assert "geometria_kmeans_014_v1.json" in _fuente_del_cuaderno()


def test_la_celda_de_imports_del_cuaderno_06_se_ejecuta():
    """Ejecuta de verdad la celda 1, que es solo imports y rutas.

    Las comprobaciones de arriba miran CADENAS, y eso dejo pasar un fallo real:
    al promover la geometria, `ventanas_015.cargar_clases_desde_014` se renombro a
    `cargar_clases_criticidad`, el cuaderno siguio importando el nombre viejo y
    ninguna prueba de texto lo noto. Un `exec` de esta celda si lo nota, cuesta
    menos de un segundo y no toca el CSV ni el modelo.

    Deliberadamente NO se ejecuta mas alla de la celda 1: de la 4 en adelante el
    cuaderno abre la base de 566 MB, que no pertenece a una prueba unitaria.
    """
    cuaderno = json.loads(CUADERNO_06.read_text(encoding="utf-8"))
    celdas_codigo = [c for c in cuaderno["cells"] if c["cell_type"] == "code"]
    espacio: dict = {"__name__": "__main__"}
    exec(compile("".join(celdas_codigo[0]["source"]), "<celda 1 del cuaderno 06>", "exec"), espacio)
    # Nombres que las celdas siguientes dan por sentados.
    for nombre in ("ROOT", "cargar_clases_criticidad", "cargar_geometria_014"):
        assert nombre in espacio, f"la celda 1 no dejo definido {nombre!r}"
