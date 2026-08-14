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
import shlex
import subprocess
import sys
import zlib
from pathlib import Path

ES_WINDOWS = os.name == "nt"
ES_MAC = sys.platform == "darwin"

# El titulo que llevan las ventanas que abre este modulo. Sirve para dos cosas: que el
# usuario sepa de que es cada ventana con cinco abiertas, y que una prueba pueda
# reconocerlas sin depender del comando que llevan dentro.
TITULO = "CriticidadCHEC"


def _carpeta_temporal() -> Path:
    """Una carpeta temporal SIN espacios, que es la condicion que impone
    `CommandString`. En macOS `TMPDIR` es `/var/folders/...` y no los lleva, pero
    comprobarlo cuesta una linea y el fallo que evita -- una ventana que no abre y no
    dice por que -- cuesta una tarde."""
    ruta = Path(os.environ.get("TMPDIR") or "/tmp")
    return Path("/tmp") if " " in str(ruta) else ruta


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


def _abrir_windows(comando: list[str], *, etiqueta: str,
                   entorno: dict[str, str] | None, directorio: Path | None) -> bool:
    """`start` con TITULO explicito. Omitirlo hace que `start` tome la primera ruta
    entrecomillada como titulo de la ventana y no ejecute nada -- el mismo fallo que
    Ghostty, en otro sistema."""
    partes = ["cmd", "/c", "start", f"{TITULO} -- {etiqueta}"]
    if directorio is not None:
        partes += ["/D", str(directorio)]
    partes += ["cmd", "/k", subprocess.list2cmdline(comando)]
    try:
        ambiente = dict(os.environ, **(entorno or {}))
        return subprocess.run(partes, env=ambiente,
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
