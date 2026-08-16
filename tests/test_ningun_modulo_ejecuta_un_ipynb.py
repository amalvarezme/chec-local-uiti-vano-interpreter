"""Ningun modulo del proyecto vuelve a ejecutar un cuaderno.

## Que se esta fijando, y por que hace falta fijarlo

Durante meses, la unica copia del codigo de los cinco tableros vivio dentro de un
`.ipynb`, y `aplicaciones/_comun/cuaderno.py` los ejecutaba con `exec()` sobre el JSON.
Funcionaba, y traia tres costos que no se pagan una vez y ya:

  * **El codigo no era navegable.** Ningun `grep`, ningun `import`, ninguna herramienta
    de refactor veia esas 15.000 lineas. Se editaban dentro de un editor de cuadernos o
    a mano sobre el JSON.
  * **Cambiarlo era un parche de texto.** La aplicacion del simulador reescribia seis
    marcas literales dentro de una copia del cuaderno; mover una linea del original
    rompia la aplicacion en un archivo que no la mencionaba.
  * **Las pruebas afirmaban sobre texto.** Y por eso se volvian mudas en silencio: una
    marca que deja de aparecer hace que un `not in` no pueda fallar.

Los cinco ya son modulos de `src/chec_tableros/`. Esta prueba existe para que no vuelva
a colarse un sexto: es barata, no depende de datos y falla en el sitio.

## Por que se mira el CODIGO y no el texto

Los modulos de `src/chec_tableros/` explican en su docstring que antes se ejecutaban con
`exec()`, y esa explicacion es justo lo que hay que conservar -- es la mitad de por que
existen. Una busqueda por texto la convertiria en un fallo y empujaria a borrarla. Con
`ast` se pregunta por la LLAMADA, que es lo unico que puede volver a pasar.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

# Donde vive el codigo que construye y sirve los tableros. `tests/` queda fuera a
# proposito: una prueba puede necesitar `exec` para comprobar precisamente esto.
ARBOLES = ("aplicaciones", "src", "scripts")

# Se prohiben las dos: `eval` sobre el JSON de un cuaderno es el mismo agujero con otro
# nombre, y ninguna de las dos tiene un uso legitimo en este proyecto.
PROHIBIDAS = {"exec", "eval"}


def _modulos() -> list[Path]:
    return sorted(py for arbol in ARBOLES
                  for py in (RAIZ / arbol).rglob("*.py")
                  if ".venv" not in py.parts)


def test_hay_modulos_que_revisar():
    """Guarda de la prueba de abajo: si el recorrido deja de encontrar archivos, la
    afirmacion pasaria vacia y no diria nada."""
    assert len(_modulos()) > 50


def test_ningun_modulo_ejecuta_codigo_de_un_cuaderno():
    culpables = []
    for py in _modulos():
        arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for nodo in ast.walk(arbol):
            if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                    and nodo.func.id in PROHIBIDAS):
                culpables.append(f"{py.relative_to(RAIZ)}:{nodo.lineno} "
                                 f"{nodo.func.id}(...)")
    assert not culpables, (
        "estas llamadas ejecutan codigo en tiempo de ejecucion:\n  "
        + "\n  ".join(culpables)
        + "\n\nEl codigo de un tablero va en `src/chec_tableros/` y se importa."
    )


def test_no_queda_ningun_cuaderno_de_tablero():
    """`notebooks/base_apps/` desaparecio: sus cinco cuadernos eran la fuente de las
    cinco aplicaciones y hoy no queda ninguno.

    Se afirma sobre `notebooks/` entero y no sobre esa carpeta, porque una carpeta que
    ya no existe hace que `glob` devuelva vacio y la prueba pase por el motivo
    equivocado -- pasaria igual si alguien moviera los cuadernos a otro sitio.

    El unico `.ipynb` que queda es `notebooks/05_mil_vano_ventana.ipynb`, y ese se
    ejecuta COMO CUADERNO -- entrena el modelo MIL --, que es exactamente para lo que
    sirve un cuaderno. Ademas es salida generada de `scripts/generate_notebook_10.py`.
    """
    cuadernos = sorted(p.relative_to(RAIZ).as_posix()
                       for p in (RAIZ / "notebooks").rglob("*.ipynb"))
    assert cuadernos == ["notebooks/05_mil_vano_ventana.ipynb"], cuadernos
    assert not (RAIZ / "notebooks" / "base_apps").exists()


def test_el_ejecutor_de_cuadernos_ya_no_existe():
    """`aplicaciones/_comun/cuaderno.py` era quien leia el JSON y ejecutaba las celdas.

    Se borra en vez de dejarlo sin llamar: un ayudante que sigue ahi es una invitacion
    a volver a usarlo, y su docstring defendia -- con razon, mientras el codigo vivio en
    el cuaderno -- que ejecutar el `.ipynb` era mejor que duplicarlo. Esa disyuntiva ya
    no existe: no hay copia que desincronizar porque no hay cuaderno.
    """
    assert not (RAIZ / "aplicaciones" / "_comun" / "cuaderno.py").exists()


@pytest.mark.parametrize("app", sorted(
    p.name for p in (RAIZ / "aplicaciones").iterdir()
    if p.is_dir() and p.name[0].isdigit()))
def test_ninguna_aplicacion_importa_el_ejecutor(app: str):
    """Ni por el nombre del modulo ni a traves de `construccion.py`."""
    for py in sorted((RAIZ / "aplicaciones" / app).glob("*.py")):
        arbol = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                nombres = {a.name for a in nodo.names}
            elif isinstance(nodo, ast.ImportFrom):
                nombres = {nodo.module or ""}
            else:
                continue
            assert "cuaderno" not in nombres, (
                f"{py.relative_to(RAIZ)}:{nodo.lineno} importa el ejecutor de cuadernos")
