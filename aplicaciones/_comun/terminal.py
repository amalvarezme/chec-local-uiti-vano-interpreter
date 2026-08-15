"""Abrir una VENTANA DE TERMINAL NUEVA para un comando, sin que Ghostty se la quede.

## El problema, medido y no razonado

En macOS, quien recibe un archivo al hacer doble clic lo decide la atadura de
LaunchServices de cada maquina, no el repositorio. Y esa atadura se cambia sin
querer desde el "Abrir con" del Finder. Con Ghostty instalado (comprobado en la
maquina del usuario con `lsregister -dump`, y otra vez el 2026-08-14):

    Ghostty reclama  .command, .tool, .sh, .zsh, .csh, .pl
                     con CFBundleTypeRole = Editor        <-- EDITOR, no shell

O sea que un `.command` que le toque a Ghostty **no se ejecuta**: solo se lleva el
foco a la sesion que ya estuviera abierta. Y lo peor de ese fallo es donde deja el
arreglo -- si el script no llega a correr, nada de lo que se escriba DENTRO del
script puede salvarlo.

Terminal.app, en cambio, reclama:

    com.apple.terminal.shell-script  (los .command)      con rol Shell
    com.apple.terminal.settings      (los .terminal)     con rol Editor

y **`.terminal` no lo reclama nadie mas** -- verificado en el mismo volcado. Ese es
el hueco por el que pasa este modulo: se escribe un perfil de ventana (`.terminal`,
que es un plist) y se le entrega a Terminal.app POR NOMBRE, con `open -a Terminal`.
`-a` no es una preferencia, es una orden: LaunchServices no consulta ninguna
atadura. Es lo mismo que hacen los seis `Iniciar.app/Contents/MacOS/iniciar`, y
esto existe para que el menu no tenga que repetirlo en Python.

## Lo que NO se puede usar aqui, y por que

**`osascript` nunca.** Pedirle a Terminal por AppleScript que abra o cierre una
ventana exige el permiso de Automatizacion. Sin el la llamada no falla: se queda
COLGADA esperando un dialogo que puede salir detras de otra ventana (medido: 19 s y
subiendo, con la ventana muerta en pantalla). `open` no pasa por Apple Events y no
pide ningun permiso.

**`webbrowser`, `os.system`, `sh -c` con el comando dentro:** ninguno abre una
ventana nueva; heredan la que haya, que es justo lo contrario de lo que se pide.

## Los dos ajustes del perfil, medidos uno por uno

    RunCommandAsShell falso   Terminal corre el comando DENTRO de un shell de login:
                              el comando acaba, el shell sigue vivo, la ventana se
                              queda abierta para siempre.
    RunCommandAsShell cierto  el comando ES la sesion, y al acabar la ventana se
                              cierra sola -- que es la mitad de lo que "Cerrar todo"
                              promete.

Y con el cierto, `CommandString` **no lo interpreta ningun shell**: se ejecuta tal
cual. Medido: con `exec` delante no arranca, entre comillas tampoco, y una ruta con
espacios no arranca. De ahi el trampolin -- un guion en una carpeta sin espacios --
que es lo unico que se le pasa a Terminal.

`shellExitAction = 0` es lo que cierra la ventana al salir. Hacen falta LOS DOS.

## Windows

`start` es una orden interna de `cmd`, asi que se invoca a traves de el. El primer
argumento entrecomillado es el TITULO de la ventana y no el comando: omitirlo hace
que `start` tome la primera ruta entrecomillada como titulo y no ejecute nada. Es
el equivalente exacto del fallo de Ghostty, en otro sistema.
"""
from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ES_WINDOWS = os.name == "nt"
ES_MAC = sys.platform == "darwin"

# El titulo que llevan las ventanas que abre este modulo. Sirve para dos cosas: que el
# usuario sepa de que es cada ventana con cinco abiertas, y que una prueba pueda
# reconocerlas sin depender del comando que llevan dentro.
TITULO = "CriticidadCHEC"

# Como se llaman los trampolines, y por tanto la unica huella por la que una ventana
# nuestra se puede reconocer despues. Se declara aqui arriba porque la escriben
# `_abrir_mac`/`_abrir_windows` y la lee `cerrar_ventanas`: tenerla en dos sitios era la
# manera de que el barrido dejara de encontrar lo que el lanzador acababa de crear.
#
# Casa RUTAS, no nombres sueltos, y quien la usa comprueba ademas que la ruta este en la
# carpeta temporal. Las dos cosas juntas, porque el nombre a secas es demasiado facil de
# llevar encima sin ser una ventana: cualquier `grep` de estos temporales -- una prueba,
# una sonda, el propio `ps | grep` de quien esta mirando -- lleva el patron ENTERO en su
# linea de ordenes, y con un criterio flojo el barrido le mandaria un `SIGTERM`.
_PATRON_TRAMPOLIN = re.compile(r"\S*/chec-[^/\s]+-ventana\.(?:sh|bat)")


def _carpeta_temporal() -> Path:
    """Donde se escriben el trampolin y el perfil.

    `tempfile.gettempdir()` y no `TMPDIR` a pelo: esa variable es de POSIX y en Windows
    no existe, asi que leerla directamente caia a `/tmp`, que alli no es ninguna carpeta.
    `gettempdir` resuelve `%TEMP%` en Windows y `TMPDIR` en macOS.

    La regla de los espacios es **solo de macOS**: alli el `CommandString` del perfil no
    lo interpreta ningun shell, asi que una ruta con un espacio no arranca -- medido. En
    Windows la ruta viaja entrecomillada dentro del `start` y un `%TEMP%` bajo
    `C:\\Users\\Nombre Apellido\\...` pasa entero.
    """
    ruta = Path(tempfile.gettempdir())
    if ES_MAC and " " in str(ruta):
        return Path("/tmp")
    return ruta


def _huella(partes: str) -> str:
    """Una huella corta y estable del comando, para nombrar sus temporales.

    Nombrarlos solo por la aplicacion fue un fallo real y costo una sesion: la carpeta
    se llama `06_simulador` tanto en el clon principal como en cualquier worktree de
    git, asi que las dos copias escribian EL MISMO archivo y la ultima que corriera se
    lo quedaba. El trampolin apuntaba a un worktree ya borrado, salia con 126, y como el
    perfil cierra la ventana al terminar lo unico que se veia era un parpadeo.

    `zlib.crc32` y no un hash criptografico: aqui no hay nada que resistir, solo dos
    rutas que distinguir, y es biblioteca estandar pura como todo este paquete.
    """
    return f"{zlib.crc32(partes.encode('utf-8')) & 0xFFFFFFFF:08x}"


def _guion_posix(comando: list[str], entorno: dict[str, str] | None,
                 directorio: Path | None) -> str:
    """El trampolin: un guion de shell que fija el entorno y salta al comando.

    Las variables van DENTRO del guion y no en el `env` de un `Popen`, porque quien
    lanza la ventana es `open` y su entorno no llega al comando: Terminal.app es un
    proceso aparte que ya estaba corriendo, con el suyo propio.
    """
    lineas = ["#!/bin/sh",
              "# Generado por _comun/terminal.py en cada arranque. No se edita: se",
              "# reescribe. Si esta viejo, es que sobrevivio a la ventana que lo uso.",
              ""]
    if directorio is not None:
        lineas.append(f"cd {shlex.quote(str(directorio))} || exit 1")
    for clave, valor in (entorno or {}).items():
        lineas.append(f"export {clave}={shlex.quote(valor)}")
    # El destino se comprueba ANTES de saltar. Sin esto, un ejecutable ausente sale con
    # 126 y la ventana se cierra encima del error: el usuario ve un parpadeo y no tiene
    # donde leer nada. Un mensaje que se puede leer separa "esto se rompio" de "estoy
    # abriendo un acceso directo a una copia que ya borre".
    lineas += [
        "",
        f"DESTINO={shlex.quote(comando[0])}",
        'if [ ! -x "$DESTINO" ] && ! command -v "$DESTINO" > /dev/null 2>&1; then',
        '    printf \'\\n  No se encontro el arranque de esta aplicacion:\\n\\n    %s\\n\\n\' "$DESTINO"',
        "    printf '  Suele pasar al abrir un acceso directo a una copia del repositorio\\n'",
        "    printf '  que ya se borro. Abrelo desde la carpeta del repositorio de ahora.\\n\\n'",
        "    printf '  Pulsa Intro para cerrar esta ventana.\\n'",
        "    read -r _",
        "    exit 1",
        "fi",
        "",
        " ".join(shlex.quote(parte) for parte in comando),
        "SALIDA=$?",
        "",
        # Un fallo se PARA a que lo lean. Con `shellExitAction = 0` la ventana se cierra
        # sola al salir, asi que sin esta pausa se cerraria sobre su propio mensaje de
        # error y el usuario no tendria donde leer que paso.
        'if [ "$SALIDA" -ne 0 ]; then',
        '    echo ""',
        '    echo "  Termino con error (codigo $SALIDA)."',
        '    echo "  Lee el mensaje de arriba y pulsa Intro para cerrar esta ventana."',
        "    read -r _",
        "fi",
        "exit 0",
        "",
    ]
    return "\n".join(lineas)


_PERFIL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>name</key>
\t<string>{titulo}</string>
\t<key>type</key>
\t<string>Window Settings</string>
\t<key>CommandString</key>
\t<string>{trampolin}</string>
\t<key>RunCommandAsShell</key>
\t<true/>
\t<key>shellExitAction</key>
\t<integer>0</integer>
</dict>
</plist>
"""


def hay_ventanas() -> bool:
    """Si este sistema sabe abrir una ventana de terminal nueva.

    En Linux no se intenta: no hay un emulador que se pueda dar por instalado, y
    adivinar entre `gnome-terminal`, `konsole`, `xterm`... es como se termina fallando
    en la maquina de alguien. Alli el menu sigue lanzando en segundo plano, que es lo
    que hacia antes de todo esto y funciona.
    """
    return ES_MAC or ES_WINDOWS


def abrir_ventana(comando: list[str], *, etiqueta: str,
                  entorno: dict[str, str] | None = None,
                  directorio: Path | None = None) -> bool:
    """Abre una ventana de terminal NUEVA corriendo `comando`. Dice si lo consiguio.

    `etiqueta` distingue las ventanas entre si y nombra los temporales; `entorno` son
    las variables que el comando necesita, que viajan dentro del trampolin porque el
    entorno de quien llama no llega hasta Terminal.app.

    Devuelve `False` -- sin levantar -- cuando el sistema no sabe abrir ventanas o
    cuando el lanzador falla. Quien llama decide si eso es un fallo o si se cae al
    arranque en segundo plano: aqui no se puede saber cual de las dos cosas quiere.
    """
    if not hay_ventanas():
        return False
    if ES_WINDOWS:
        return _abrir_windows(comando, etiqueta=etiqueta, entorno=entorno,
                              directorio=directorio)
    return _abrir_mac(comando, etiqueta=etiqueta, entorno=entorno,
                      directorio=directorio)


def _abrir_mac(comando: list[str], *, etiqueta: str,
               entorno: dict[str, str] | None, directorio: Path | None) -> bool:
    temporal = _carpeta_temporal()
    marca = _huella("\0".join([etiqueta, *comando, str(directorio)]))
    trampolin = temporal / f"chec-{etiqueta}-{marca}-ventana.sh"
    perfil = temporal / f"chec-{etiqueta}-{marca}-ventana.terminal"
    try:
        trampolin.write_text(_guion_posix(comando, entorno, directorio),
                             encoding="utf-8")
        trampolin.chmod(0o755)
        perfil.write_text(_PERFIL.format(titulo=TITULO, trampolin=trampolin),
                          encoding="utf-8")
    except OSError:
        return False
    # Por NOMBRE primero y por IDENTIFICADOR de bundle despues. El segundo intento
    # cubre el unico modo de fallo que este lanzador si puede remontar: que Terminal.app
    # no este donde `open` la busca por nombre -- renombrada, movida, o un macOS
    # recortado por una politica de empresa --. LaunchServices indexa el identificador
    # de verdad. Sin ese segundo intento no pasa absolutamente nada y no queda donde
    # leerlo.
    for lanzador in (["/usr/bin/open", "-a", "Terminal", str(perfil)],
                     ["/usr/bin/open", "-b", "com.apple.Terminal", str(perfil)]):
        try:
            if subprocess.run(lanzador, capture_output=True, timeout=20).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def _guion_windows(comando: list[str], entorno: dict[str, str] | None,
                   directorio: Path | None) -> str:
    """El trampolin de Windows: un `.bat` que fija el entorno y salta al comando.

    Existe por los mismos dos motivos que el de POSIX y por uno mas, propio de `cmd`:
    meter el comando entero dentro de `cmd /c start ... cmd /c "..."` obliga a anidar
    comillas dentro de comillas, y ahi `cmd` las come de una forma que depende de cuantas
    haya. Con el comando en un archivo, a `start` se le pasa UNA ruta y no hay nada que
    anidar.

    `setlocal` acota las variables a esta ventana. `pause` SOLO si algo fallo: la ventana
    se cierra al terminar -- eso es lo que permite que "Cerrar todo" cierre tambien las
    ventanas -- y sin la condicion se cerraria sobre su propio mensaje de error.
    """
    lineas = ["@echo off",
              "REM Generado por _comun/terminal.py en cada arranque. No se edita: se",
              "REM reescribe. Si esta viejo, es que sobrevivio a la ventana que lo uso.",
              "setlocal"]
    if directorio is not None:
        # `/d` cambia tambien de unidad. Sin el, un repositorio en D: y un `cmd` que
        # arranca en C: dejan el `cd` sin efecto y el comando corre desde otro sitio.
        #
        # Y se COMPRUEBA, igual que el `[ ! -x "$DESTINO" ]` del trampolin de POSIX y por
        # el mismo caso: un acceso directo a una copia del repositorio que ya se borro.
        # Sin la comprobacion el `.bat` sigue adelante en el directorio equivocado y el
        # error que sale despues no se parece en nada a su causa.
        lineas += [
            f'cd /d "{directorio}"',
            "if errorlevel 1 (",
            "    echo.",
            "    echo   No se encontro la carpeta de esta aplicacion:",
            f"    echo     {directorio}",
            "    echo.",
            "    echo   Suele pasar al abrir un acceso directo a una copia del",
            "    echo   repositorio que ya se borro.",
            "    echo.",
            "    pause",
            "    exit /b 1",
            ")",
        ]
    for clave, valor in (entorno or {}).items():
        # Las comillas van alrededor de TODA la asignacion, que es la forma que no mete
        # el espacio final dentro del valor: `set "X=uno"` y no `set X=uno `.
        lineas.append(f'set "{clave}={valor}"')
    lineas += [
        "",
        subprocess.list2cmdline(comando),
        "if errorlevel 1 (",
        "    echo.",
        "    echo   Termino con error. Lee el mensaje de arriba.",
        # `timeout` y no `pause`, y esto es una CONCESION medida a como apaga Windows.
        #
        # En POSIX "Cerrar todo" senala al GRUPO, asi que se lleva por delante tambien al
        # trampolin y la ventana se cierra. En Windows el respaldo es `taskkill /T`, que
        # baja por los descendientes y NUNCA por los ancestros: alcanza a la aplicacion y
        # deja vivo al `cmd` que corre este archivo. Ese `cmd` ve un codigo distinto de
        # cero -- porque a su hijo lo mataron -- y con un `pause` se quedaria esperando
        # una tecla PARA SIEMPRE, con el puerto ya libre y la ventana muerta en pantalla.
        # O sea, justo lo contrario de lo que "Cerrar todo" promete.
        #
        # Con `timeout` el error se puede leer, cualquier tecla lo salta, y una ventana
        # que nadie esta mirando se cierra sola. Los 45 s son para leer un traceback sin
        # prisa; el caso frecuente -- apagar desde el menu -- no los espera nadie.
        "    echo   Esta ventana se cierra sola en 45 segundos.",
        "    timeout /t 45",
        ")",
        "",
    ]
    return "\r\n".join(lineas)


def _abrir_windows(comando: list[str], *, etiqueta: str,
                   entorno: dict[str, str] | None, directorio: Path | None) -> bool:
    """Una consola NUEVA con `start`, y el comando en un `.bat` aparte.

    `start` es una orden interna de `cmd`, asi que se invoca a traves de el. Y el primer
    argumento entrecomillado es el **TITULO** de la ventana, no el comando: omitirlo hace
    que `start` tome la primera ruta entrecomillada como titulo y no ejecute nada. Es el
    equivalente exacto del fallo de Ghostty en el otro sistema -- el lanzador "funciona"
    y no corre nada --, asi que el titulo va siempre y explicito.
    """
    temporal = _carpeta_temporal()
    marca = _huella("\0".join([etiqueta, *comando, str(directorio)]))
    trampolin = temporal / f"chec-{etiqueta}-{marca}-ventana.bat"
    # `oem` y NO `utf-8`: `cmd` lee los archivos por lotes con la pagina de codigos OEM
    # de la consola (cp850 / cp437 en un Windows en espaniol), no con UTF-8. Un
    # `C:\Users\Jose Garcia\...` con tilde escrito en UTF-8 llega ahi como mojibake, el
    # `cd /d` falla y la ventana arranca el comando desde la carpeta equivocada -- un
    # fallo que no se parece en nada a su causa. `oem` es el alias que Python da a esa
    # misma pagina, asi que el archivo se escribe en la codificacion en que se va a leer.
    #
    # El respaldo cubre el caso de que el codec no exista (no es Windows), que solo pasa
    # en una prueba: aqui abajo ya se sabe que si lo es.
    for codificacion in ("oem", "utf-8"):
        try:
            trampolin.write_text(_guion_windows(comando, entorno, directorio),
                                 encoding=codificacion)
            break
        except (LookupError, UnicodeEncodeError):
            continue
        except OSError:
            return False
    else:
        return False
    # `/c` y no `/k`: `/k` deja la consola abierta PARA SIEMPRE despues de que el comando
    # termine, y entonces "Cerrar todo" liberaria el puerto dejando la ventana muerta en
    # pantalla -- justo lo contrario de lo que promete. La pausa en caso de error la pone
    # el trampolin, que sabe si hubo error; `/k` no.
    partes = ["cmd", "/c", "start", f"{TITULO} -- {etiqueta}", "/D",
              str(directorio or temporal), "cmd", "/c", str(trampolin)]
    try:
        return subprocess.run(partes, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------ cerrar lo que no se cerro solo


def _tabla_de_procesos() -> list[tuple[int, int, str]]:
    """`(pid, ppid, linea de ordenes)` de todo lo que corre ahora. Vacia si no se puede.

    La linea de ordenes es lo unico que distingue una ventana nuestra de cualquier otra,
    y en Windows no la da ni `tasklist` ni `taskkill`: hay que pedirsela a PowerShell.
    Cuesta cerca de medio segundo, y por eso esto NO se llama al vigilar -- que corre
    cada 2,5 s -- sino solo al apagar, que pasa una vez.
    """
    if ES_WINDOWS:
        orden = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | "
                 "ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId) "
                 "$($_.CommandLine)\" }"]
    else:
        orden = ["/bin/ps", "-eo", "pid=,ppid=,command="]
    try:
        salida = subprocess.run(orden, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    tabla = []
    for linea in salida.stdout.splitlines():
        partes = linea.strip().split(None, 2)
        if len(partes) < 3:
            continue
        try:
            tabla.append((int(partes[0]), int(partes[1]), partes[2]))
        except ValueError:
            continue
    return tabla


def _es_una_ventana_nuestra(orden: str) -> bool:
    """Si esa linea de ordenes es la de un trampolin que escribio este modulo.

    Dos condiciones, y hacen falta las dos: que la ruta se llame como un trampolin y que
    ESTE en la carpeta temporal donde este modulo los escribe. Solo con el nombre, todo
    lo que nombre un trampolin sin serlo -- una prueba, una sonda, un `ps | grep` de
    quien esta mirando -- pasaria por ventana y se llevaria un `SIGTERM`. La carpeta es
    lo que separa "corre esto" de "habla de esto".
    """
    temporal = str(_carpeta_temporal()).rstrip("/\\")
    return any(str(Path(ruta).parent).rstrip("/\\") == temporal
               for ruta in _PATRON_TRAMPOLIN.findall(orden))


def ventana_viva(etiqueta: str) -> bool:
    """Si sigue trabajando la ventana que se abrio con esa `etiqueta`.

    El trampolin se llama `chec-<etiqueta>-<marca>-ventana.sh` y vive en la tabla de
    procesos mientras la ventana tiene algo que hacer, asi que preguntar por el es
    preguntar si esa apertura sigue en pie.

    Existe porque quien abre una ventana NO se queda con un proceso al que vigilar --
    lo lanzo Terminal.app -- y sin esto la unica forma de enterarse de que una apertura
    murio es agotar el plazo de espera entero.

    Se compara la CARPETA del trampolin, igual que en `cerrar_ventanas`: un `ps | grep
    chec-simulador-ventana.sh` lleva ese texto en su propia linea de comando y sin
    mirar la ruta se contaria a si mismo.
    """
    marca = f"chec-{etiqueta}-"
    for _pid, _ppid, orden in _tabla_de_procesos():
        if not _es_una_ventana_nuestra(orden):
            continue
        if any(Path(ruta).name.startswith(marca)
               for ruta in _PATRON_TRAMPOLIN.findall(orden)):
            return True
    return False


def _procesos_en_ventana(tabla: list[tuple[int, int, str]] | None = None) -> list[int]:
    """Los pid de lo que corre dentro de una ventana que abrio este modulo.

    El criterio es el trampolin, que solo escribe este modulo. Cualquier otro -- el
    nombre del interprete, la terminal en la que esta, un `read` colgado -- acaba
    senialando procesos de alguien por parecerse a los nuestros.
    """
    if tabla is None:
        tabla = _tabla_de_procesos()
    return [pid for pid, _, orden in tabla if _es_una_ventana_nuestra(orden)]


def _ascendencia(pid: int, padres: dict[int, int] | None = None) -> list[int]:
    """Los pid de los que cuelga `pid`, de su padre hacia arriba."""
    if padres is None:
        padres = {p: pp for p, pp, _ in _tabla_de_procesos()}
    cadena, visto = [], {pid}
    actual = padres.get(pid, 0)
    while actual > 1 and actual not in visto:
        cadena.append(actual)
        visto.add(actual)
        actual = padres.get(actual, 0)
    return cadena


def cerrar_ventanas() -> list[int]:
    """Cierra las ventanas de terminal que abrio este modulo. Devuelve a quien alcanzo.

    Una ventana se cierra sola cuando su comando **termina bien**: lo pide el
    `shellExitAction` del perfil. Cuando termina mal no, y es a proposito -- el trampolin
    se para en un `read` para que el error se pueda leer --, asi que basta con que otra
    cosa tenga el puerto de un tablero (`SALIDA_PUERTO_AJENO`) para que quede una ventana
    parada para siempre. Esa ventana no tiene puerto, de modo que el apagado por puertos
    ni la ve, y se acumula una por intento.

    Esto es lo unico del proyecto que las alcanza, y por eso se llama al FINAL de
    `apagar_todo`: primero cada aplicacion sale por su puerta -- soltando su puerto y,
    en el simulador, sus kernels -- y su ventana se va sola; lo que quede aqui es lo que
    no tenia puerta.

    Nunca se barre la ventana desde la que se esta llamando. Es una ventana como las
    otras: la del menu. Cerrarla aqui mataria al menu a mitad de apagar lo demas, y
    ademas sobra, porque se cierra sola en cuanto su propio comando termina.
    """
    tabla = _tabla_de_procesos()
    padres = {pid: ppid for pid, ppid, _ in tabla}
    yo = os.getpid()
    propias = {yo, *_ascendencia(yo, padres)}

    alcanzadas = []
    for pid in _procesos_en_ventana(tabla):
        if pid in propias:
            continue
        try:
            if ES_WINDOWS:
                # `taskkill /T` baja por los descendientes, que es donde vive el comando
                # de la ventana. Nunca sube: por eso hay que alcanzar cada pid de la
                # cadena, y por eso se recorren todos los que casan y no solo el primero.
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError,
                subprocess.SubprocessError):
            # Ya no esta -- lo normal cuando se alcanza primero a su padre -- o no es
            # nuestro. Ninguna de las dos es un fallo del apagado.
            continue
        alcanzadas.append(pid)
    return alcanzadas
