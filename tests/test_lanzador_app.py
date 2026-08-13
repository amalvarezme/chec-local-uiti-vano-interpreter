"""El lanzador de doble clic de macOS: `Iniciar.app`.

## Por que un `.app` y no el `.command` que ya habia

Un `.command` es un archivo a merced de quien LaunchServices tenga atado a esa
extension, y esa atadura no viaja con el repositorio: la fija cada maquina. Medido en
una con Ghostty instalado:

  - `open iniciar.command` con el manejador por defecto (Terminal.app): abre una ventana
    nueva y ejecuta el script.
  - `open -a Ghostty iniciar.command`: **no ejecuta nada**. Ghostty se declara manejador
    de `.command` en su `Info.plist` con `CFBundleTypeRole = Editor` -- editor, no shell
    --, asi que se lleva el foco a la sesion que ya estaba abierta y ahi se acaba todo.

Lo peor de ese fallo es donde deja el arreglo: si el script no llega a ejecutarse, nada
de lo que se escriba DENTRO del script puede salvarlo. Por eso el lanzador es un bundle.
LaunchServices no "abre" un `.app` con la aplicacion de otro: lo LANZA.

## Los dos papeles del mismo archivo

`Contents/MacOS/iniciar` se llama a si mismo una vez, y se distingue por `CHEC_EN_VENTANA`:

  1. **Sin la variable** -- es el doble clic. Abre una ventana NUEVA de Terminal que
     vuelve a lanzarlo con la variable puesta, y sale. Nunca reutiliza la sesion en la
     que uno este trabajando.
  2. **Con la variable** -- ya esta dentro de esa ventana. Arranca la aplicacion, y
     cuando la aplicacion termina -- porque se pulso su boton de cerrar, o Ctrl+C --
     cierra la ventana que abrio.

Las dos ramas se comprueban aqui con dobles de `osascript` y de `python3` en el PATH, que
apuntan como los llamaron. Sin eso, la unica forma de probarlo seria a ojo delante de una
pantalla, que es como estos dos papeles se cruzaron en primer lugar.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"

TODAS = sorted(d for d in APPS.iterdir()
               if d.is_dir() and not d.name.startswith((".", "_")))
IDS = [d.name for d in TODAS]

BUNDLE = "Iniciar.app"
EJECUTABLE = f"{BUNDLE}/Contents/MacOS/iniciar"
PLIST = f"{BUNDLE}/Contents/Info.plist"


# ------------------------------------------------------------------------ estructura


@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_cada_aplicacion_trae_su_lanzador_de_doble_clic(app: Path):
    assert (app / PLIST).is_file(), f"{app.name} no tiene {PLIST}"
    assert (app / EJECUTABLE).is_file(), f"{app.name} no tiene {EJECUTABLE}"


@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_el_ejecutable_del_bundle_tiene_permiso_de_ejecucion(app: Path):
    """Sin el bit de ejecucion macOS no lanza el bundle: da "la aplicacion esta
    danada". Git conserva ese bit, asi que perderlo es cosa de quien cree el archivo,
    y no se nota hasta que alguien hace doble clic en otra maquina."""
    assert os.access(app / EJECUTABLE, os.X_OK), f"{app.name}/{EJECUTABLE} no es ejecutable"


@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_el_plist_declara_lo_que_launchservices_necesita(app: Path):
    """`CFBundleExecutable` que no apunte al archivo real, o un `CFBundlePackageType`
    que no sea `APPL`, y macOS deja de tratarlo como aplicacion -- que es justo lo que
    este bundle existe para garantizar."""
    datos = plistlib.loads((app / PLIST).read_bytes())
    assert datos["CFBundleExecutable"] == "iniciar"
    assert datos["CFBundlePackageType"] == "APPL"
    # El guion bajo de la carpeta no vale en un identificador de bundle, asi que se
    # compara con la forma que si vale. Que ademas no se repitan lo fija la prueba de
    # abajo: LaunchServices indexa por identificador y dos bundles iguales se pisan.
    assert app.name.replace("_", "-") in datos["CFBundleIdentifier"], (
        f"{app.name}: el identificador no lo nombra -- {datos['CFBundleIdentifier']}")
    # Sin esto, un lanzador que abre una ventana y se va deja un icono suelto en el Dock.
    assert datos.get("LSUIElement") is True


def test_los_identificadores_no_se_repiten():
    identificadores = {
        app.name: plistlib.loads((app / PLIST).read_bytes())["CFBundleIdentifier"]
        for app in TODAS}
    assert len(set(identificadores.values())) == len(identificadores), identificadores


def test_los_seis_lanzadores_son_el_mismo_archivo():
    """Seis copias del mismo script es exactamente como una se queda atras. Si algun dia
    una necesita algo propio, esa diferencia tiene que ser deliberada y romper aqui."""
    textos = {app.name: (app / EJECUTABLE).read_bytes() for app in TODAS}
    assert len(set(textos.values())) == 1, (
        "los lanzadores se separaron: " + ", ".join(textos))


# -------------------------------------------------------------------- comportamiento


@pytest.fixture
def dobles(tmp_path):
    """Pone un `osascript` y un `python3` de mentira delante en el PATH.

    Los dos apuntan como los llamaron en un archivo y no hacen nada mas. Es lo que
    permite comprobar las dos ramas del lanzador sin abrir ninguna ventana.
    """
    binarios = tmp_path / "bin"
    binarios.mkdir()
    registro = tmp_path / "llamadas.txt"
    for nombre in ("osascript", "python3"):
        doble = binarios / nombre
        doble.write_text(
            "#!/bin/sh\n"
            f'{{ echo "=== {nombre}"; echo "cwd: $(pwd)"; '
            'for a in "$@"; do echo "arg: $a"; done; '
            'echo "--- entrada"; cat; } >> ' + f'"{registro}"\n',
            encoding="utf-8")
        doble.chmod(0o755)

    def correr(app: Path, *, en_ventana: bool):
        ambiente = dict(os.environ, PATH=f"{binarios}:{os.environ['PATH']}")
        ambiente.pop("CHEC_EN_VENTANA", None)
        if en_ventana:
            ambiente["CHEC_EN_VENTANA"] = "1"
        hecho = subprocess.run([str(app / EJECUTABLE)], env=ambiente,
                               capture_output=True, text=True, timeout=30)
        assert hecho.returncode == 0, hecho.stderr
        return registro.read_text(encoding="utf-8") if registro.exists() else ""

    return correr


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_el_doble_clic_abre_una_ventana_nueva_y_no_arranca_nada_todavia(dobles):
    """La rama que arregla el fallo: aunque el doble clic acabe en una sesion que ya
    estaba abierta, lo unico que se hace ahi es pedir una ventana NUEVA."""
    app = APPS / "01_clima"
    llamadas = dobles(app, en_ventana=False)

    assert "=== osascript" in llamadas, "no pidio ninguna ventana"
    assert "do script" in llamadas, "no pidio una ventana NUEVA de Terminal"
    assert "CHEC_EN_VENTANA=1" in llamadas, (
        "la ventana nueva tiene que recibir la marca, o volveria a abrir otra sin parar")
    assert str(app / EJECUTABLE) in llamadas, "no se pasa a si mismo por ruta absoluta"
    assert "=== python3" not in llamadas, (
        "arranco la aplicacion en la sesion equivocada: eso es justo lo que se corrige")


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_dentro_de_la_ventana_arranca_la_aplicacion_y_luego_cierra_la_ventana(dobles):
    app = APPS / "01_clima"
    llamadas = dobles(app, en_ventana=True)

    assert "=== python3" in llamadas, "no arranco la aplicacion"
    assert "arg: ../_comun/gestor.py" in llamadas
    assert "arg: iniciar" in llamadas
    # Y despues, no antes: cerrar la ventana mientras la aplicacion sirve la mataria.
    assert llamadas.index("=== python3") < llamadas.index("=== osascript"), (
        "cerro la ventana antes de que la aplicacion terminara")
    assert "close" in llamadas.split("=== osascript", 1)[1], (
        "no cierra la ventana al terminar: el usuario cierra el tablero y le queda una "
        "ventana de terminal muerta, que es lo que se pidio evitar")


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_cada_lanzador_arranca_la_aplicacion_de_su_propia_carpeta(app: Path, dobles):
    """El gestor deduce la aplicacion del directorio de trabajo, asi que un lanzador que
    no se situe en su carpeta arrancaria otra -- o ninguna. En el bundle el riesgo es
    mayor que en el `.command`: el ejecutable esta tres niveles mas abajo."""
    llamadas = dobles(app, en_ventana=True)
    # El gestor se llama por ruta RELATIVA, asi que el directorio de trabajo es lo unico
    # que decide que aplicacion arranca. Se comprueba donde estaba parado al llamarlo.
    assert f"cwd: {app}\n" in llamadas.split("=== python3", 1)[1], (
        f"{app.name}: el lanzador no se situo en su carpeta antes de llamar al gestor")
    assert "arg: ../_comun/gestor.py" in llamadas
