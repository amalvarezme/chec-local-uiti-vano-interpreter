"""Lo de las aplicaciones locales que solo se rompe en Windows.

Windows no puede probarse desde aqui, y esa es justamente la razon de que este archivo
exista: los tres fallos que fija son de los que no se ven al leer el codigo en un Mac
-- una constante que en Windows no existe, una opcion de socket que en Windows significa
lo contrario, y un lanzador que en Windows es otro archivo.

Lo que se comprueba no es "corre en Windows" -- eso pide una maquina Windows --, sino
que el codigo no tome decisiones que ALLI son imposibles o peligrosas.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"
COMUN = APPS / "_comun"

TODAS = sorted(d for d in APPS.iterdir()
               if d.is_dir() and not d.name.startswith((".", "_")))
IDS = [d.name for d in TODAS]

# Lo que Windows NO tiene. `SIGKILL` es el que muerde: existe en POSIX, no en Windows, y
# nombrarlo revienta con AttributeError en el momento de evaluarlo -- no al importar,
# sino en mitad del apagado, que es cuando menos se puede depurar.
SIN_WINDOWS = ("SIGKILL", "SIGHUP", "SIGQUIT", "killpg", "getpgid", "getpgrp",
               "start_new_session", "os.fork", "geteuid")


def _fuera_de_condicional(ruta: Path, nombre: str) -> bool:
    """Si `nombre` aparece en una rama que Windows tambien ejecuta.

    Se acepta dentro de un `if`/`else` que consulte la plataforma, y dentro de un
    `try/except AttributeError`. Fuera de eso, Windows llega ahi.
    """
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    protegidos: set[int] = set()
    for nodo in ast.walk(arbol):
        prueba = None
        if isinstance(nodo, ast.If):
            prueba = nodo.test
        elif isinstance(nodo, ast.IfExp):
            prueba = nodo.test
        if prueba is None:
            continue
        texto = ast.unparse(prueba)
        if any(m in texto for m in ("ES_WINDOWS", "os.name", "sys.platform",
                                    "_REUSAR_DIRECCION")):
            for hijo in ast.walk(nodo):
                protegidos.add(id(hijo))

    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.Name, ast.Attribute)):
            continue
        texto = ast.unparse(nodo)
        if not any(texto.endswith(n) or texto == n for n in (nombre,)):
            continue
        if id(nodo) not in protegidos:
            return True
    return False


@pytest.mark.parametrize("nombre", SIN_WINDOWS)
def test_ningun_modulo_comun_usa_algo_que_windows_no_tiene(nombre: str):
    """Si lo usa, tiene que ser detras de una pregunta por la plataforma.

    `menu.py` llegaba a `signal.SIGKILL` en la escalada del apagado sin preguntar nada:
    en Windows eso es un `AttributeError` en mitad de "Cerrar todo", con las aplicaciones
    ya a medio apagar.
    """
    for ruta in sorted(COMUN.glob("*.py")):
        assert not _fuera_de_condicional(ruta, nombre), (
            f"{ruta.name} usa {nombre} en una rama que Windows tambien ejecuta")


def test_el_reuso_de_direccion_no_se_activa_en_windows():
    """`SO_REUSEADDR` significa cosas OPUESTAS en los dos sistemas.

    En POSIX permite volver a tomar un puerto que quedo en TIME_WAIT, que es lo que hace
    falta para cerrar y reabrir un tablero enseguida. En Windows permite que un SEGUNDO
    proceso se ate a un puerto que ya esta escuchando y se lo robe -- sin error, sin
    aviso, y con dos servidores repartiendose las peticiones.

    Ahi tambien esta el sondeo: con la opcion puesta, `puerto_libre` daria por libre en
    Windows un puerto que otra aplicacion esta sirviendo.
    """
    ruta = COMUN / "servidor.py"
    fuente = ruta.read_text(encoding="utf-8")
    assert re.search(r"allow_reuse_address\s*=\s*(not\s+\w*WINDOWS|_REUSAR\w*)", fuente), (
        "allow_reuse_address tiene que depender de la plataforma, no ser True fijo")
    # Y el sondeo tiene que hacerse la misma pregunta: si no, `puerto_libre` daria por
    # libre en Windows un puerto que otra aplicacion esta sirviendo ahora mismo.
    assert not _fuera_de_condicional(ruta, "setsockopt"), (
        "el setsockopt del sondeo no esta detras de la pregunta por la plataforma")


@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_cada_aplicacion_trae_su_lanzador_de_windows(app: Path):
    """`Iniciar.app` es de macOS. En Windows el doble clic es el `.bat`, y tiene que
    existir para las seis o esa maquina se queda sin puerta de entrada."""
    for nombre in ("iniciar.bat", "instalar.bat"):
        assert (app / nombre).is_file(), f"{app.name} no tiene {nombre}"


@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_el_bat_se_situa_y_deja_ver_el_error(app: Path):
    """Dos cosas que en Windows se pagan caras.

    El `cd /d "%~dp0"` porque el gestor deduce la aplicacion del directorio de trabajo, y
    el doble clic no arranca necesariamente en la carpeta del archivo.

    El `pause` porque la consola de un `.bat` se CIERRA al terminar: sin el, un error se
    lleva por delante su propio mensaje y el usuario ve una ventana que parpadea. Es el
    mismo cuidado que el lanzador de macOS tiene con `read`.
    """
    texto = (app / "iniciar.bat").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in texto, f"{app.name}/iniciar.bat no se situa"
    assert "pause" in texto, f"{app.name}/iniciar.bat cierra la ventana sobre el error"


def test_las_pruebas_de_apagado_no_se_intentan_en_windows():
    """`tests/test_menu_apagado.py` levanta procesos con `start_new_session` y los mata
    con `killpg`: en Windows no existe ninguno de los dos. Sin la marca, esa suite no
    falla por lo que mide -- falla por el sistema, que es ruido."""
    fuente = (RAIZ / "tests" / "test_menu_apagado.py").read_text(encoding="utf-8")
    assert 'sys.platform == "win32"' in fuente or "os.name == \"nt\"" in fuente, (
        "esa suite no se salta en Windows")


def test_los_lanzadores_llevan_el_final_de_linea_de_su_sistema():
    """Cual le toca a cada uno no puede depender del `core.autocrlf` de quien clone.

    `cmd.exe` tropieza con archivos por lotes en LF, y `/bin/sh` no arranca un guion
    cuyo `#!` termina en CR -- da "bad interpreter", que no menciona el final de linea
    por ningun lado. Se fija en `.gitattributes` para que el checkout lo resuelva.
    """
    reglas = (RAIZ / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"^\*\.bat\s+text\s+eol=crlf", reglas, re.M), (
        "los .bat tienen que salir en CRLF")
    assert re.search(r"^\*\.command\s+text\s+eol=lf", reglas, re.M), (
        "los .command tienen que salir en LF")
    # Los dos guiones del bundle de macOS no tienen extension, asi que ninguna regla
    # por extension los alcanza y hay que nombrarlos.
    for pieza in ("Iniciar.app/Contents/MacOS/iniciar",
                  "Iniciar.app/Contents/Resources/ventana"):
        assert re.search(rf"^{re.escape(pieza)}\s+text\s+eol=lf", reglas, re.M), (
            f"{pieza} puede acabar en CRLF y dejar de arrancar")


@pytest.mark.skipif(sys.platform == "win32", reason="en Windows el checkout es CRLF")
@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_los_guiones_de_shell_no_llevan_retorno_de_carro(app: Path):
    """El fallo que esto evita es mudo de verdad: un `#!/bin/sh\\r` da
    "bad interpreter: no such file or directory", que hace pensar que falta `sh`."""
    for pieza in ("iniciar.command", "instalar.command",
                  "Iniciar.app/Contents/MacOS/iniciar",
                  "Iniciar.app/Contents/Resources/ventana"):
        ruta = app / pieza
        if ruta.exists():
            assert b"\r\n" not in ruta.read_bytes(), f"{app.name}/{pieza} trae CRLF"
