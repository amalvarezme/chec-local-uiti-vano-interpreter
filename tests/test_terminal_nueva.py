"""La regla de Ghostty, escrita como prueba para que no haya que recordarla.

## Que es lo que se repite

Este fallo ha vuelto tres veces, y siempre por el mismo sitio: **algo del proyecto
entrega un archivo a macOS y deja que LaunchServices decida quien lo abre.** Medido en
la maquina del usuario con `lsregister -dump`, la ultima vez el 2026-08-14:

    Ghostty       reclama  .command, .tool, .sh, .zsh, .csh, .pl
                  con CFBundleTypeRole = Editor                  <-- EDITOR, no shell
    Terminal.app  reclama  com.apple.terminal.shell-script  (rol Shell)
                           com.apple.terminal.settings      (rol Editor)

Un `.command` que le toque a Ghostty **no se ejecuta**: solo se lleva el foco a la sesion
ya abierta. Y lo que hace este fallo tan caro es donde deja el arreglo -- si el script no
llega a correr, nada de lo que se escriba DENTRO del script puede salvarlo. El sintoma es
un parpadeo, o directamente nada, sin ningun sitio donde leer que paso.

## La regla, en una linea

**Todo camino que abra una ventana de terminal tiene que nombrar a Terminal.app.**
`open -a Terminal <perfil.terminal>` -- o `open -b com.apple.Terminal` de respaldo --,
nunca `open <archivo>` a secas y nunca un `.command` como destino de doble clic.

`-a` no es una preferencia: es una orden. LaunchServices no consulta ninguna atadura, y
por eso es el unico camino que no depende de la maquina. `.terminal` ademas no lo reclama
nadie mas que Terminal.app, de modo que ese formato es el hueco por el que se pasa.

## Y la otra mitad: nunca `osascript`

Pedirle a Terminal por AppleScript que abra o cierre una ventana exige el permiso de
Automatizacion. Sin el la llamada **no falla**: se queda COLGADA esperando un dialogo que
puede salir detras de otra ventana. Medido: 19 s y subiendo, con la ventana muerta en
pantalla. Por eso la ventana se cierra sola con `shellExitAction` del perfil y no
mandandole nada a Terminal.

Estas pruebas leen los lanzadores como TEXTO. No abren ninguna ventana: `open` sobre un
bundle desde un entorno sin interfaz devuelve `-10669`, asi que el ultimo salto solo lo
puede probar una persona delante de la pantalla. Lo que si se puede fijar es que ningun
camino del repositorio vuelva a dejarle la decision al sistema.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"
COMUN = APPS / "_comun"

from ayudas_aplicaciones import locales  # noqa: E402

CARPETAS = locales()
IDS = [d.name for d in CARPETAS]

sys.path.insert(0, str(COMUN))
import terminal as _terminal  # noqa: E402


def _sin_prosa(fuente: str) -> str:
    """El CODIGO, sin comentarios ni docstrings.

    Hace falta porque estos archivos explican por extenso el fallo del que se cuidan:
    la palabra `osascript` y un `open` de ejemplo aparecen en la prosa de casi todos.
    Buscarlos sobre el texto crudo hace que la prueba falle justo por lo que la
    documentacion hace bien, que es la peor manera de gastar la atencion de nadie.
    """
    sin_docs = re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", fuente)
    return "\n".join(l for l in sin_docs.splitlines() if not l.lstrip().startswith("#"))


def _fuentes_de_lanzamiento() -> dict[str, str]:
    """Todo lo que puede abrir una ventana: los seis bundles y el modulo comun."""
    fuentes = {}
    for carpeta in CARPETAS:
        guion = carpeta / "Iniciar.app" / "Contents" / "MacOS" / "iniciar"
        if guion.exists():
            fuentes[f"{carpeta.name}/Iniciar.app"] = _sin_prosa(
                guion.read_text(encoding="utf-8"))
    fuentes["_comun/terminal.py"] = _sin_prosa(
        (COMUN / "terminal.py").read_text(encoding="utf-8"))
    return fuentes


# --------------------------------------------------------- la regla, sobre el texto


@pytest.mark.parametrize("nombre", sorted(_fuentes_de_lanzamiento()))
def test_todo_lanzador_nombra_a_terminal_app(nombre):
    """Nadie abre una ventana sin decir con QUE la abre.

    Un `open` sin `-a`/`-b` consulta la atadura de la maquina, y ahi es donde Ghostty se
    lleva el archivo. Es el fallo que este proyecto ya pago tres veces.
    """
    fuente = _fuentes_de_lanzamiento()[nombre]
    aperturas = re.findall(r"^[^#\n]*\bopen\b[^\n]*$", fuente, re.M)
    aperturas = [a for a in aperturas if "open(" not in a and "urlopen" not in a
                 and "write_text" not in a and ".open" not in a]
    assert aperturas, f"{nombre} deberia abrir una ventana en alguna parte"
    for linea in aperturas:
        assert ("-a Terminal" in linea or "-b com.apple.Terminal" in linea
                or '"-a", "Terminal"' in linea
                or '"-b", "com.apple.Terminal"' in linea), (
            f"{nombre}: `{linea.strip()}` deja que LaunchServices elija quien abre el "
            "archivo, y con Ghostty instalado eso significa que no se ejecuta nada")


@pytest.mark.parametrize("nombre", sorted(_fuentes_de_lanzamiento()))
def test_ningun_lanzador_usa_osascript(nombre):
    """Sin el permiso de Automatizacion, `osascript` no falla: se queda colgado."""
    assert "osascript" not in _fuentes_de_lanzamiento()[nombre]


@pytest.mark.parametrize("nombre", sorted(_fuentes_de_lanzamiento()))
def test_ningun_lanzador_entrega_un_command_a_open(nombre):
    """El destino que se le pasa a `open` es un `.terminal`, nunca un `.command`.

    Aunque se nombre a Terminal.app, entregarle un `.command` vuelve a atar el arranque a
    un formato que otro terminal reclama. El perfil `.terminal` no lo reclama nadie mas.
    """
    fuente = _fuentes_de_lanzamiento()[nombre]
    for linea in re.findall(r"^[^#\n]*\bopen\b[^\n]*$", fuente, re.M):
        assert ".command" not in linea, (
            f"{nombre}: `{linea.strip()}` le entrega un `.command` a `open`")


@pytest.mark.parametrize("carpeta", CARPETAS, ids=IDS)
def test_el_doble_clic_de_cada_app_es_el_bundle(carpeta):
    """Cada aplicacion trae su `Iniciar.app`, que es el destino del doble clic.

    El `abrir-en-terminal.command` de al lado se conserva a proposito -- sirve desde una
    terminal ya abierta, y es el camino de Linux --, pero ya no se llama como el bundle:
    con el nombre viejo (`iniciar.command`) el doble clic caia ahi. Lo que no puede
    faltar nunca es el bundle: sin el, el unico camino de doble clic vuelve a ser el
    `.command`.
    """
    bundle = carpeta / "Iniciar.app" / "Contents" / "MacOS" / "iniciar"
    assert bundle.exists(), f"{carpeta.name} se quedo sin lanzador de doble clic"
    # El bit de ejecucion solo existe donde hay permisos POSIX. En Windows, NTFS no lo
    # tiene y `st_mode` sale siempre `0o666`: la comprobacion no fallaria por un bundle
    # sin permisos, sino por el sistema de archivos. Que el bundle ESTE si se comprueba
    # en los dos, que es la mitad que puede perderse en un commit.
    if os.name != "nt":
        assert bundle.stat().st_mode & 0o111, f"{bundle} no es ejecutable"


# ------------------------------------------------- el modulo que abre las ventanas


def test_el_perfil_cierra_la_ventana_al_terminar():
    """Los DOS ajustes, y hacen falta los dos.

    `RunCommandAsShell` falso deja la ventana abierta para siempre -- el comando acaba y
    el shell de login sigue vivo --, y sin `shellExitAction = 0` tampoco se cierra. Que
    la ventana se cierre sola es la mitad de lo que "Cerrar todo" promete: el menu no
    cierra ventanas, hace terminar el comando que las sostiene.
    """
    fuente = (COMUN / "terminal.py").read_text(encoding="utf-8")
    assert "<key>RunCommandAsShell</key>\n\\t<true/>" in fuente.replace("\t", "\\t")
    assert "<key>shellExitAction</key>\n\\t<integer>0</integer>" in fuente.replace("\t", "\\t")


def test_el_trampolin_lleva_el_entorno_dentro():
    """Las variables van DENTRO del guion y no en el `env` de un `Popen`.

    Quien abre la ventana es `open`, y su entorno no llega al comando: Terminal.app es
    otro proceso, que ya estaba corriendo con el suyo. Sin esto el tablero arranca sin
    `MENU_CRITICIDAD` y su boton "Volver al menu" no sabe a donde volver.
    """
    # `PurePosixPath` y no `Path`: el guion que se genera aqui es de shell y su `cd` se
    # escribe con `str(directorio)`. Un `Path("/tmp")` en Windows se rinde como `\tmp`,
    # con lo que la prueba fallaba por como escribe rutas la plataforma que la corre y
    # no por lo que hace el trampolin. El destino es POSIX siempre: se dice asi.
    guion = _terminal._guion_posix(["/bin/echo", "hola"],
                                   {"MENU_CRITICIDAD": "http://127.0.0.1:8800/"},
                                   PurePosixPath("/tmp"))
    # Sin comillas alrededor de la URL, y esta bien: `shlex.quote` solo las pone cuando
    # hacen falta. Se comprueba el EXPORT y su valor, no como quedo citado.
    assert "export MENU_CRITICIDAD=http://127.0.0.1:8800/" in guion
    assert "cd /tmp || exit 1" in guion
    # Y un valor con espacios si tiene que salir citado, o el `export` parte en dos.
    con_espacios = _terminal._guion_posix(["/bin/echo"], {"X": "uno dos"}, None)
    assert "export X='uno dos'" in con_espacios


def test_el_trampolin_cita_lo_que_pueda_llevar_espacios():
    """Una ruta con espacios, comillas o `&` tiene que pasar entera.

    El repositorio puede vivir en `~/Mis Documentos/...`, y una ruta partida por un
    espacio produce un comando que no existe y una ventana que se cierra sobre el error.
    """
    guion = _terminal._guion_posix(
        ["/ruta con espacios/py", "--app", "/otra 'rara'/x"], None, None)
    assert "'/ruta con espacios/py'" in guion
    assert "'/otra '\"'\"'rara'\"'\"'/x'" in guion


def test_el_trampolin_comprueba_su_destino_antes_de_saltar():
    """Un destino ausente sale con 126 y la ventana se cierra encima del error: el
    usuario ve un parpadeo y no tiene donde leer nada. Es el sintoma que costo una
    sesion entera de diagnostico."""
    guion = _terminal._guion_posix(["/no/existe"], None, None)
    assert 'if [ ! -x "$DESTINO" ]' in guion
    assert "read -r _" in guion


def test_el_trampolin_se_para_cuando_algo_falla():
    """Con la ventana cerrandose sola, un error sin pausa no se puede leer."""
    guion = _terminal._guion_posix(["/bin/true"], None, None)
    assert 'if [ "$SALIDA" -ne 0 ]; then' in guion


def test_los_temporales_se_nombran_por_el_comando_entero():
    """Dos copias del repositorio no pueden escribir el mismo archivo.

    `06_simulador` se llama igual en el clon principal y en cada worktree de git. Cuando
    los temporales se nombraban solo por la aplicacion, la ultima copia que corriera se
    quedaba el archivo y la otra saltaba a una ruta borrada. Sintoma: doble clic,
    parpadeo, nada.
    """
    a = _terminal._huella("\0".join(["simulador", "/repo/aplicaciones/06_simulador/x"]))
    b = _terminal._huella("\0".join(["simulador", "/otro/aplicaciones/06_simulador/x"]))
    assert a != b
    # Y estable: el mismo comando tiene que reusar su archivo en vez de sembrar uno por
    # arranque en la carpeta temporal.
    assert a == _terminal._huella("\0".join(
        ["simulador", "/repo/aplicaciones/06_simulador/x"]))


def test_la_carpeta_temporal_en_mac_nunca_lleva_espacios(monkeypatch):
    """`CommandString` no lo interpreta ningun shell: en macOS una ruta con un espacio
    no arranca -- medido --, asi que ahi se cae a `/tmp`.

    Se parchea `tempfile.gettempdir` y no la variable `TMPDIR`: `gettempdir` CACHEA su
    resultado en `tempfile.tempdir`, asi que mover la variable despues de la primera
    llamada no cambia nada y la prueba pasaria por casualidad.
    """
    monkeypatch.setattr(_terminal, "ES_MAC", True)
    monkeypatch.setattr(_terminal.tempfile, "gettempdir", lambda: "/var/con espacio/T")
    assert _terminal._carpeta_temporal() == Path("/tmp")
    monkeypatch.setattr(_terminal.tempfile, "gettempdir", lambda: "/var/folders/xy/T")
    assert _terminal._carpeta_temporal() == Path("/var/folders/xy/T")


def test_la_carpeta_temporal_en_windows_admite_espacios(monkeypatch):
    """En Windows la ruta viaja entrecomillada dentro del `start`, asi que un `%TEMP%`
    bajo `C:\\Users\\Nombre Apellido\\...` pasa entero. Caerse a `/tmp` alli seria
    escribir el trampolin en una carpeta que no existe -- que es lo que hacia leer
    `TMPDIR` a pelo, una variable que en Windows no esta definida."""
    monkeypatch.setattr(_terminal, "ES_MAC", False)
    monkeypatch.setattr(_terminal.tempfile, "gettempdir",
                        lambda: r"C:\Users\Nombre Apellido\AppData\Local\Temp")
    assert _terminal._carpeta_temporal() == Path(
        r"C:\Users\Nombre Apellido\AppData\Local\Temp")


# ------------------------------------------------- lo que se le dice al que lo abre
#
# Esto se fija como prueba porque ya se contradijo a si mismo una vez: los seis README de
# aplicacion decian "en macOS haz doble clic en Iniciar.app, no en iniciar.command" y el
# README de arriba, en la misma carpeta, decia "en macOS doble clic sobre el `.command`".
# Alguien que siga la instruccion equivocada se encuentra con que no pasa nada, y no
# tiene forma de saber que la culpa es de la documentacion.


@pytest.mark.parametrize("carpeta", CARPETAS, ids=IDS)
def test_cada_readme_dice_que_abrir_en_cada_sistema(carpeta):
    """`Iniciar.app` en macOS y `iniciar.bat` en Windows, dicho en la misma frase."""
    readme = carpeta / "README.md"
    assert readme.exists(), f"{carpeta.name} se quedo sin README"
    texto = readme.read_text(encoding="utf-8")
    assert "A qué le doy doble clic" in texto, (
        f"{carpeta.name}/README.md no dice a que hay que darle doble clic")
    bloque = texto[texto.index("A qué le doy doble clic"):][:1200]
    assert "`Iniciar.app`" in bloque and "macOS" in bloque
    assert "`iniciar.bat`" in bloque and "Windows" in bloque


def test_ningun_readme_manda_al_command_en_mac():
    """La instruccion contraria, que es la que hubo que corregir.

    Se busca la frase entera y no la palabra `.command`: los README hablan de el a
    proposito -- se conserva para lanzarlo a mano y es el camino de Linux --, y prohibir
    la palabra obligaria a no poder explicarlo.
    """
    for readme in [*(c / "README.md" for c in CARPETAS), APPS / "README.md"]:
        texto = readme.read_text(encoding="utf-8")
        for frase in ("En **macOS** doble clic sobre el `.command`",
                      "en macOS doble clic sobre el `.command`",
                      "En macOS haz doble clic en `iniciar.command`"):
            assert frase not in texto, f"{readme} manda al `.command` en macOS"


def test_el_readme_de_arriba_trae_la_tabla_de_los_tres_sistemas():
    """Una tabla, tres filas, y el que la lee no tiene que deducir nada."""
    texto = (APPS / "README.md").read_text(encoding="utf-8")
    tabla = texto[texto.index("## Cómo se usan"):][:1400]
    assert "| **macOS** |" in tabla and "`Iniciar.app`" in tabla
    assert "| **Windows** |" in tabla and "`iniciar.bat`" in tabla
    assert "| Linux |" in tabla and "./abrir-en-terminal.command" in tabla


# ------------------------------------------------------------- el camino de Windows
#
# Aqui no se puede ejecutar nada de esto: no hay Windows. Lo que si se puede fijar es la
# FORMA del comando y del trampolin, que es donde estan los tres fallos que `cmd` regala
# y que no avisan -- la ventana se abre igual y no corre nada, o se queda abierta para
# siempre. Los tres se comprueban abajo sobre el texto que se genera.


def test_windows_pasa_el_titulo_a_start_siempre():
    """`start` toma su primer argumento entrecomillado como TITULO de la ventana.

    Sin titulo, `start "C:\\ruta\\al\\trampolin.bat"` interpreta la ruta como titulo,
    abre una consola vacia y no ejecuta nada. Es el equivalente exacto del fallo de
    Ghostty en el otro sistema: el lanzador "funciona" y no corre nada.
    """
    fuente = _sin_prosa((COMUN / "terminal.py").read_text(encoding="utf-8"))
    assert '"cmd", "/c", "start", f"{TITULO} -- {etiqueta}"' in fuente


def test_windows_cierra_la_consola_al_terminar():
    """`cmd /c` y NUNCA `cmd /k`.

    `/k` deja la consola abierta para siempre despues de que el comando termine, asi que
    "Cerrar todo" liberaria el puerto y dejaria la ventana muerta en pantalla -- lo
    contrario de lo que promete, y lo contrario de lo que hace macOS con
    `shellExitAction`.
    """
    fuente = _sin_prosa((COMUN / "terminal.py").read_text(encoding="utf-8"))
    assert '"cmd", "/c", str(trampolin)' in fuente
    assert "/k" not in fuente, "una consola con `cmd /k` no se cierra nunca"


def test_el_trampolin_de_windows_lleva_entorno_directorio_y_pausa():
    """Las tres cosas que el trampolin tiene que hacer, y una que no.

    `cd /d` cambia tambien de UNIDAD: sin la `/d`, un repositorio en `D:` con un `cmd`
    que arranca en `C:` deja el `cd` sin efecto y el comando no encuentra nada.
    """
    guion = _terminal._guion_windows(
        [r"C:\Python\python.exe", "gestor.py"],
        {"MENU_CRITICIDAD": "http://127.0.0.1:8800/"},
        Path(r"C:\repo\aplicaciones\01_clima"))
    assert guion.startswith("@echo off")
    assert r'cd /d "C:\repo\aplicaciones\01_clima"' in guion
    # Las comillas van alrededor de TODA la asignacion, que es la forma que no mete un
    # espacio final dentro del valor.
    assert 'set "MENU_CRITICIDAD=http://127.0.0.1:8800/"' in guion
    # Y la parada SOLO si algo fallo: la ventana se cierra al terminar, asi que una
    # parada incondicional la dejaria esperando en el caso normal.
    assert guion.count("if errorlevel 1 (") == 2   # el `cd` y el comando


def test_el_trampolin_de_windows_comprueba_el_cd():
    """`cd /d` que falla y un `.bat` que sigue adelante es el mismo caso del worktree
    borrado que ya costo una sesion, pero en Windows: el comando arranca desde otro
    directorio y el error que sale despues no se parece en nada a su causa."""
    guion = _terminal._guion_windows(["x.exe"], None, Path(r"D:\no\existe"))
    cd = guion[guion.index("cd /d"):]
    assert cd.startswith('cd /d "D:\\no\\existe"')
    assert "if errorlevel 1 (" in cd[:200]
    assert "exit /b 1" in cd


def test_el_trampolin_de_windows_no_se_queda_esperando_una_tecla():
    """`timeout` y NO `pause` tras un fallo del comando.

    En POSIX "Cerrar todo" senala al GRUPO y se lleva tambien al trampolin, asi que la
    ventana se cierra. En Windows el respaldo es `taskkill /T`, que baja por los
    descendientes y nunca por los ancestros: deja vivo al `cmd` que corre el `.bat`, que
    ve un codigo distinto de cero porque a su hijo lo mataron. Con un `pause` ahi, la
    ventana se quedaria PARA SIEMPRE con el puerto ya libre -- lo contrario de lo que
    "Cerrar todo" promete.
    """
    guion = _terminal._guion_windows(["x.exe"], None, None)
    assert "timeout /t 45" in guion
    # Sin directorio no hay bloque de `cd`, asi que no puede quedar ningun `pause`.
    assert "pause" not in guion


def test_el_trampolin_de_windows_usa_saltos_de_linea_de_windows():
    """Un `.bat` con saltos `\\n` sueltos falla de formas que no se parecen a su causa:
    `cmd` lee la linea con el retorno de carro pegado al ultimo argumento."""
    guion = _terminal._guion_windows(["x.exe"], None, None)
    assert "\r\n" in guion and "\n" not in guion.replace("\r\n", "")


def test_windows_y_mac_nombran_su_trampolin_igual_de_distinto():
    """La huella del comando entero, tambien alli: dos copias del repositorio no pueden
    escribir el mismo `.bat`."""
    fuente = _sin_prosa((COMUN / "terminal.py").read_text(encoding="utf-8"))
    assert fuente.count('_huella("\\0".join([etiqueta, *comando, str(directorio)]))') == 2


def test_sin_ventanas_no_se_intenta_abrir_ninguna():
    """En Linux no hay un emulador que se pueda dar por instalado, y adivinar entre
    `gnome-terminal`, `konsole` y `xterm` es como se termina fallando en la maquina de
    alguien. Alli el menu lanza en segundo plano, que es lo que hacia antes."""
    assert _terminal.hay_ventanas() == (sys.platform == "darwin" or __import__("os").name == "nt")


def test_windows_no_captura_la_salida_de_start():
    """`capture_output` en la ventana de Windows colgaba el menu para siempre.

    `start` vuelve al instante, pero los pipes los HEREDA todo el arbol que arranca en la
    consola nueva -- el gestor, la aplicacion, Voila y sus kernels --, y `communicate()`
    espera un EOF que no llega mientras el servidor viva. El `timeout` no rescata nada:
    en Windows CPython responde al plazo con `kill()` y otro `communicate()` SIN plazo, y
    ese `kill()` solo alcanza al `cmd /c start`, que ya murio.

    Medido: con `timeout=3` y un nieto de 25 s, `run()` volvio en 24,9 s -- espero al
    NIETO, no al plazo. Con un tablero detras no volvia nunca, y el hilo se quedaba ahi
    ANTES de `_esperar`: la tarjeta decia "levantando el servidor" indefinidamente con el
    tablero ya sirviendo, hasta caer al respaldo en segundo plano y perder la ventana.
    """
    fuente = _sin_prosa((COMUN / "terminal.py").read_text(encoding="utf-8"))
    windows = fuente.split("def _abrir_windows")[1]
    # Solo ESTA funcion: mas abajo hay un `capture_output` legitimo, el del
    # `tasklist` con que se cierran las ventanas que no se cerraron solas.
    windows = windows.split("\ndef ")[0]
    assert "capture_output" not in windows, \
        "capturar la salida de `start` cuelga al menu hasta que muera el tablero"
    assert "stdout=subprocess.DEVNULL" in windows
    assert "stderr=subprocess.DEVNULL" in windows
