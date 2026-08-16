"""El lanzador de doble clic de macOS: `Iniciar.app`.

## Por que un `.app` y no el `.command` que ya habia

Un `.command` es un archivo a merced de quien LaunchServices tenga atado a esa
extension, y esa atadura no viaja con el repositorio: la fija cada maquina. Medido en
una con Ghostty instalado:

  - `open abrir-en-terminal.command` con el manejador por defecto (Terminal.app): abre una ventana
    nueva y ejecuta el script.
  - `open -a Ghostty abrir-en-terminal.command`: **no ejecuta nada**. Ghostty se declara manejador
    de `.command` en su `Info.plist` con `CFBundleTypeRole = Editor` -- editor, no shell
    --, asi que se lleva el foco a la sesion que ya estaba abierta y ahi se acaba todo.

Lo peor de ese fallo es donde deja el arreglo: si el script no llega a ejecutarse, nada
de lo que se escriba DENTRO del script puede salvarlo. Por eso el lanzador es un bundle.
LaunchServices no "abre" un `.app` con la aplicacion de otro: lo LANZA.

## Los dos archivos, y por que son dos

  1. `Contents/MacOS/iniciar` -- lo que corre el doble clic. NO arranca la aplicacion:
     escribe un perfil de ventana de Terminal (`.terminal`, un plist) y se lo pasa a
     Terminal.app. Asi la ventana es siempre NUEVA, nunca la sesion en la que uno
     estuviera trabajando.
  2. `Contents/Resources/ventana` -- lo que corre YA DENTRO de esa ventana: arranca la
     aplicacion y, si termina con error, se para a que lean el mensaje.

Son dos archivos y no uno con un interruptor porque asi no hay forma de que el papel 1
se llame a si mismo: una ventana que abre otra ventana sin parar es un fallo que en una
maquina se ve, pero en una prueba automatica no.

Y no se usa `osascript` en ninguno de los dos, tambien por algo medido: pedirle a
Terminal por AppleScript que abra o cierre una ventana exige el permiso de
Automatizacion, y sin el la llamada no falla -- se queda COLGADA esperando un dialogo.
Es la misma trampa que la restriccion R1 del contrato. `open` no pasa por Apple Events.

Las dos ramas se comprueban con dobles de `open` y de `python3` en el PATH, que apuntan
como los llamaron. Sin eso, la unica forma de probarlo seria a ojo delante de una
pantalla, que es donde estos dos papeles se cruzaron en primer lugar.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"

from ayudas_aplicaciones import locales  # noqa: E402

TODAS = locales()
IDS = [d.name for d in TODAS]

BUNDLE = "Iniciar.app"
EJECUTABLE = f"{BUNDLE}/Contents/MacOS/iniciar"
VENTANA = f"{BUNDLE}/Contents/Resources/ventana"
PLIST = f"{BUNDLE}/Contents/Info.plist"


# ------------------------------------------------------------------------ estructura


@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_cada_aplicacion_trae_su_lanzador_de_doble_clic(app: Path):
    assert (app / PLIST).is_file(), f"{app.name} no tiene {PLIST}"
    assert (app / EJECUTABLE).is_file(), f"{app.name} no tiene {EJECUTABLE}"
    assert (app / VENTANA).is_file(), f"{app.name} no tiene {VENTANA}"


@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_el_ejecutable_del_bundle_tiene_permiso_de_ejecucion(app: Path):
    """Sin el bit de ejecucion macOS no lanza el bundle: da "la aplicacion esta
    danada". Git conserva ese bit, asi que perderlo es cosa de quien cree el archivo,
    y no se nota hasta que alguien hace doble clic en otra maquina."""
    for pieza in (EJECUTABLE, VENTANA):
        assert os.access(app / pieza, os.X_OK), f"{app.name}/{pieza} no es ejecutable"


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


@pytest.mark.parametrize("pieza", [EJECUTABLE, VENTANA])
def test_los_seis_lanzadores_son_el_mismo_archivo(pieza: str):
    """Seis copias del mismo script es exactamente como una se queda atras. Si algun dia
    una necesita algo propio, esa diferencia tiene que ser deliberada y romper aqui."""
    textos = {app.name: (app / pieza).read_bytes() for app in TODAS}
    assert len(set(textos.values())) == 1, (
        "los lanzadores se separaron: " + ", ".join(textos))


# -------------------------------------------------------------------- comportamiento


@pytest.fixture
def dobles(tmp_path):
    """Pone un `open` y un `python3` de mentira delante en el PATH.

    Los dos apuntan como los llamaron -- con su directorio de trabajo -- en un archivo, y
    no hacen nada mas. Es lo que permite comprobar los dos papeles sin abrir ninguna
    ventana ni arrancar ningun tablero.
    """
    binarios = tmp_path / "bin"
    binarios.mkdir()
    registro = tmp_path / "llamadas.txt"
    for nombre in ("open", "python3"):
        doble = binarios / nombre
        doble.write_text(
            "#!/bin/sh\n"
            f'{{ echo "=== {nombre}"; echo "cwd: $(pwd)"; '
            'for a in "$@"; do echo "arg: $a"; done; } >> ' + f'"{registro}"\n',
            encoding="utf-8")
        doble.chmod(0o755)

    def correr(app: Path, pieza: str):
        ambiente = dict(os.environ, PATH=f"{binarios}:{os.environ['PATH']}")
        hecho = subprocess.run([str(app / pieza)], env=ambiente,
                               capture_output=True, text=True, timeout=30)
        assert hecho.returncode == 0, hecho.stderr
        return registro.read_text(encoding="utf-8") if registro.exists() else ""

    return correr


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_el_doble_clic_pide_una_ventana_nueva_y_no_arranca_nada_todavia(dobles):
    """El papel 1 completo. Que NO arranque la aplicacion es la mitad del arreglo: es lo
    que garantiza que el tablero no acabe corriendo dentro de la sesion en la que el
    usuario estaba trabajando, pase lo que pase con las ataduras de LaunchServices."""
    app = APPS / "01_clima"
    llamadas = dobles(app, EJECUTABLE)

    assert "=== open" in llamadas, "no pidio ninguna ventana"
    assert "arg: -a\narg: Terminal\n" in llamadas, (
        "tiene que forzar Terminal.app por nombre: el manejador por defecto de la "
        "maquina es justo lo que no se puede dar por bueno")
    assert "=== python3" not in llamadas, (
        "arranco la aplicacion en la sesion equivocada: eso es lo que se corrige")


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_el_perfil_de_ventana_acaba_llevando_al_guion_de_su_propio_bundle(dobles):
    """La cadena entera: perfil -> trampolin -> guion de ESTE bundle.

    El eslabon del medio existe porque `CommandString` con `RunCommandAsShell` no lo
    interpreta ningun shell: se ejecuta tal cual, asi que una ruta con espacios no
    arranca -- medido. El trampolin vive en `TMPDIR`, que no los tiene.

    Y el ultimo eslabon importa por lo mismo que el resto de este archivo: si apuntara
    al bundle de otra aplicacion -- copiar y pegar entre seis carpetas iguales es lo
    natural aqui --, el doble clic de una abriria otra, en el puerto de otra.
    """
    app = APPS / "01_clima"
    llamadas = dobles(app, EJECUTABLE)

    perfil = [l[5:] for l in llamadas.splitlines()
              if l.startswith("arg: ") and l.endswith(".terminal")]
    assert perfil, f"no se le paso ningun perfil a Terminal: {llamadas}"
    datos = plistlib.loads(Path(perfil[0]).read_bytes())

    assert datos["type"] == "Window Settings"
    # Los dos, y medidos: sin `RunCommandAsShell` Terminal corre el comando dentro de un
    # shell de login que sobrevive, y la ventana no se cierra nunca.
    assert datos["RunCommandAsShell"] is True
    assert datos["shellExitAction"] == 0

    trampolin = Path(datos["CommandString"])
    assert " " not in str(trampolin), (
        "el trampolin esta en una ruta con espacios, que es justo lo que no arranca")
    assert trampolin.is_file() and os.access(trampolin, os.X_OK)
    # El trampolin lleva la ruta DENTRO, entrecomillada. Antes viajaba en un segundo
    # archivo para no tener que citarla, y ese archivo es justo el que se quedo viejo
    # cuando se borro el worktree desde el que se habia hecho doble clic.
    citada = re.search(r"^VENTANA='(.*)'$", trampolin.read_text(encoding="utf-8"),
                       re.M).group(1)
    assert citada.replace("'\\''", "'") == str(app / VENTANA)


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_dentro_de_la_ventana_se_arranca_la_aplicacion_de_esa_carpeta(app: Path, dobles):
    """El papel 2. El gestor deduce que aplicacion es del directorio de trabajo, asi que
    el `cd` es lo unico que decide cual arranca -- y aqui el guion esta tres niveles por
    debajo de su carpeta, un nivel mas que el `.command` de siempre."""
    llamadas = dobles(app, VENTANA)

    assert "=== python3" in llamadas, "no arranco la aplicacion"
    assert "arg: ../_comun/gestor.py" in llamadas
    assert "arg: iniciar" in llamadas
    assert f"cwd: {app}\n" in llamadas.split("=== python3", 1)[1], (
        f"{app.name}: no se situo en su carpeta antes de llamar al gestor")


def test_el_guion_de_la_ventana_se_para_cuando_la_aplicacion_falla():
    """Con `shellExitAction = 0` la ventana se cierra en cuanto el guion termina. Si un
    fallo saliera derecho, la ventana se cerraria encima de su propio mensaje de error y
    el doble clic no dejaria ni rastro de lo que paso -- que es el peor sitio posible
    para perder un error, porque no hay ninguna terminal a la que volver a mirar."""
    guion = (APPS / "01_clima" / VENTANA).read_text(encoding="utf-8")
    assert "read -r" in guion, "no espera a que lean el error antes de cerrarse"
    assert "-ne 0" in guion, "no distingue el fallo de la salida normal"


@pytest.fixture
def open_que_falla(tmp_path):
    """Un `open` que rechaza `-a Terminal` y apunta todo lo que le pidan.

    Es el unico modo de fallo que el lanzador puede remontar por su cuenta: Terminal.app
    renombrada o movida -- una politica de empresa, un macOS recortado -- deja el `-a`
    sin resolver. Sin respaldo, el doble clic no hace absolutamente nada y no queda
    donde leer por que: el bundle es `LSUIElement`, no tiene ventana ni terminal.
    """
    binarios = tmp_path / "bin"
    binarios.mkdir()
    registro = tmp_path / "llamadas.txt"
    doble = binarios / "open"
    doble.write_text(
        "#!/bin/sh\n"
        '{ echo "=== open"; for a in "$@"; do echo "arg: $a"; done; } >> '
        f'"{registro}"\n'
        'case "$1" in -a) exit 1 ;; esac\n'
        "exit 0\n",
        encoding="utf-8")
    doble.chmod(0o755)

    def correr(app: Path):
        ambiente = dict(os.environ, PATH=f"{binarios}:{os.environ['PATH']}")
        hecho = subprocess.run([str(app / EJECUTABLE)], env=ambiente,
                               capture_output=True, text=True, timeout=30)
        return hecho, (registro.read_text(encoding="utf-8") if registro.exists() else "")

    return correr


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_si_terminal_no_responde_por_nombre_se_pide_por_su_identificador(open_que_falla):
    """`com.apple.Terminal` es lo que LaunchServices indexa de verdad; el nombre es solo
    como se llama el archivo en disco."""
    hecho, llamadas = open_que_falla(APPS / "01_clima")

    assert "arg: -b\narg: com.apple.Terminal\n" in llamadas, (
        f"no reintento por identificador de bundle: {llamadas}")
    assert hecho.returncode == 0, "el respaldo funciono y aun asi salio con error"


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_el_lanzador_no_se_da_por_bueno_sin_haber_abierto_nada(tmp_path):
    """Con los dos intentos agotados hay que salir con error. Darse por bueno seria la
    peor version del fallo original: nada en pantalla y nadie enterado."""
    binarios = tmp_path / "bin"
    binarios.mkdir()
    doble = binarios / "open"
    doble.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    doble.chmod(0o755)
    ambiente = dict(os.environ, PATH=f"{binarios}:{os.environ['PATH']}")

    hecho = subprocess.run([str(APPS / "01_clima" / EJECUTABLE)], env=ambiente,
                           capture_output=True, text=True, timeout=30)

    assert hecho.returncode != 0


# ------------------------------------ dos copias del repositorio no se pisan


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_dos_copias_del_repositorio_no_comparten_los_archivos_temporales(dobles, tmp_path):
    """El fallo que dejo el simulador sin abrir, reproducido.

    Los archivos de `TMPDIR` se nombraban solo con la CARPETA de la aplicacion
    (`chec-06_simulador-...`), y esa carpeta se llama igual en el clon principal y en
    cualquier worktree de git. Las dos copias escribian EL MISMO archivo: la ultima que
    corriera se lo quedaba.

    Medido en la maquina del usuario: el trampolin del simulador apuntaba a
    `...-worktrees/simulador-apagado/.../ventana`, un worktree ya borrado. Al hacer doble
    clic, el trampolin salia con 126 y -- como el perfil lleva `shellExitAction` a 0 --
    la ventana se cerraba en el acto. Un parpadeo y nada mas.

    Basta con que el nombre lleve algo del CAMINO y no solo de la carpeta.
    """
    app = APPS / "06_simulador"
    otra = tmp_path / "otra-copia" / "aplicaciones" / "06_simulador"
    otra.parent.mkdir(parents=True)
    shutil.copytree(app / BUNDLE, otra / BUNDLE, symlinks=True)

    perfil_uno = _perfil_de(dobles(app, EJECUTABLE))
    perfil_dos = _perfil_de(dobles(otra, EJECUTABLE))

    assert perfil_uno != perfil_dos, (
        "las dos copias escriben el mismo perfil: la ultima le pisa el trampolin a la "
        "otra, y borrar una deja a la que queda apuntando al vacio")
    uno = plistlib.loads(Path(perfil_uno).read_bytes())["CommandString"]
    dos = plistlib.loads(Path(perfil_dos).read_bytes())["CommandString"]
    assert uno != dos, "los dos trampolines son el mismo archivo"


def _perfil_de(llamadas: str) -> str:
    perfiles = [l[5:] for l in llamadas.splitlines()
                if l.startswith("arg: ") and l.endswith(".terminal")]
    assert perfiles, f"no se le paso ningun perfil a Terminal: {llamadas}"
    return perfiles[-1]


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_el_trampolin_lleva_dentro_la_ruta_y_no_depende_de_otro_archivo(dobles):
    """El trampolin llevaba la ruta en un SEGUNDO archivo (`-destino`) para no tener que
    citarla. Eso es un puntero mas que puede quedarse viejo, y se quedo: es justo lo que
    apuntaba al worktree borrado.

    Un trampolin es un guion de shell, asi que la ruta cabe dentro entrecomillada, con
    las comillas simples escapadas. Un archivo menos y un desfase menos.
    """
    app = APPS / "06_simulador"
    perfil = _perfil_de(dobles(app, EJECUTABLE))
    trampolin = Path(plistlib.loads(Path(perfil).read_bytes())["CommandString"])
    texto = trampolin.read_text(encoding="utf-8")

    assert str(app / VENTANA) in texto, "el trampolin no lleva su destino dentro"
    assert "cat " not in texto, "el trampolin sigue leyendo la ruta de otro archivo"


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_un_destino_que_ya_no_existe_se_lee_en_la_ventana(dobles, tmp_path):
    """Con `shellExitAction` a 0, un trampolin que falla cierra la ventana al instante: el
    usuario ve un parpadeo y no tiene donde leer nada. Ese era el sintoma exacto de
    "no se abre el simulador".

    Asi que el trampolin comprueba su destino ANTES de saltar, y si no esta lo dice y se
    para. Un mensaje que se puede leer separa "esto se rompio" de "estoy abriendo un
    acceso directo a una copia que ya borre".
    """
    app = APPS / "06_simulador"
    perfil = _perfil_de(dobles(app, EJECUTABLE))
    trampolin = Path(plistlib.loads(Path(perfil).read_bytes())["CommandString"])

    # Se le rompe el destino, que es exactamente lo que hizo borrar el worktree.
    roto = trampolin.read_text(encoding="utf-8").replace(
        str(app / VENTANA), str(tmp_path / "no-existe" / "ventana"))
    trampolin.write_text(roto, encoding="utf-8")

    hecho = subprocess.run(["/bin/sh", str(trampolin)], capture_output=True, text=True,
                           input="\n", timeout=30)

    assert hecho.returncode != 0, "un destino ausente no puede darse por bueno"
    salida = hecho.stdout + hecho.stderr
    assert "no-existe" in salida, f"no dijo QUE falta: {salida!r}"
    assert "Intro" in salida, (
        f"no se paro a que lo leyeran: la ventana se cierra sobre el mensaje: {salida!r}")


# ----------------------------------- que "Cerrar todo" se lleve tambien la ventana


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
@pytest.mark.parametrize("app", TODAS, ids=IDS)
def test_la_ventana_sale_sola_cuando_la_aplicacion_termina_bien(app: Path, tmp_path):
    """La otra mitad de lo que promete el lanzador: que "Cerrar todo" cierre tambien la
    ventana de Terminal.

    La cadena es larga y ningun eslabon avisa si se rompe: el menu apaga la aplicacion ->
    `gestor.py` devuelve -> este guion devuelve -> Terminal cierra la ventana, porque el
    perfil lleva `shellExitAction` a 0. Medido de punta a punta con el simulador: el arbol
    de la ventana eran 5 procesos y despues de "Cerrar todo" no quedo ninguno, con el
    proceso de la ventana saliendo con 0.

    Lo que esta prueba protege es el ultimo eslabon barato de romper: si este guion se
    parara a que lean algo TAMBIEN en el camino bueno, la ventana se quedaria abierta
    para siempre despues de cada cierre.
    """
    binarios = tmp_path / "bin"
    binarios.mkdir()
    (binarios / "python3").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (binarios / "python3").chmod(0o755)
    ambiente = dict(os.environ, PATH=f"{binarios}:{os.environ['PATH']}")

    # Sin stdin: si el guion se parara a leer algo, esto falla en vez de colgarse.
    hecho = subprocess.run([str(app / VENTANA)], env=ambiente, capture_output=True,
                           text=True, timeout=30, stdin=subprocess.DEVNULL)

    assert hecho.returncode == 0
    assert "Intro" not in hecho.stdout, (
        "la ventana se para a que lean algo en el camino BUENO: se quedaria abierta "
        "despues de cada 'Cerrar todo'")


@pytest.mark.skipif(sys.platform != "darwin", reason="el bundle es de macOS")
def test_la_ventana_se_para_a_que_lean_el_error(tmp_path):
    """Al reves que la de arriba, y por eso van juntas: cuando la aplicacion falla, la
    ventana NO puede cerrarse sobre su propio mensaje de error."""
    binarios = tmp_path / "bin"
    binarios.mkdir()
    (binarios / "python3").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    (binarios / "python3").chmod(0o755)
    ambiente = dict(os.environ, PATH=f"{binarios}:{os.environ['PATH']}")

    hecho = subprocess.run([str(APPS / "01_clima" / VENTANA)], env=ambiente,
                           capture_output=True, text=True, timeout=30, input="\n")

    assert "codigo 3" in hecho.stdout, hecho.stdout
    assert "Intro" in hecho.stdout
