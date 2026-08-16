"""«Cerrar todo» no deja rastro: ni puerto, ni ventana de terminal, ni pestania.

`test_menu_apagado.py` ya fija la mitad que se puede medir con un socket -- que ningun
puerto quede tomado. Esta suite cubre las otras dos mitades, que son las que el usuario
ve y ninguna prueba miraba:

1. **Ventanas de terminal que sobreviven.** Cada aplicacion corre dentro de una ventana
   propia que se cierra sola *cuando su comando termina bien*. Cuando termina MAL no se
   cierra, y es a proposito: el trampolin se para en un `read` para que el error se pueda
   leer. El caso frecuente no es raro -- basta con que otra cosa tenga el puerto y el
   arranque sale con `SALIDA_PUERTO_AJENO` --, y esas ventanas se acumulan: no tienen
   puerto, asi que el apagado por puertos no las ve y no hay boton que las cierre.
2. **Pestanias del navegador.** La pagina del menu abre cada tablero con `window.open`,
   que es justo lo que le da permiso para cerrarlo despues. Guardaba ese permiso en una
   variable local y lo tiraba, asi que «Cerrar todo» apagaba los cinco servidores y
   dejaba cinco pestanias en pantalla sobre tableros muertos.
3. **El puerto del menu tomado por OTRA copia del repositorio.** El doble clic decidia
   quien tiene el puerto comparando la ruta de la carpeta contra la linea de ordenes del
   proceso. Dos clones -- o un worktree -- son dos rutas distintas, asi que el menu ya
   abierto salia como "algo que no es CriticidadCHEC": ventana de error, exit 2, y otra
   ventana atascada por cada intento. La pregunta correcta no es de quien es el proceso
   sino que contesta el puerto.

Las tres se miden contra procesos y texto de verdad, nunca con `open`: abrir una ventana
en una suite deja ventanas abiertas en la maquina de quien la corre.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"
COMUN = APPS / "_comun"

from ayudas_aplicaciones import locales  # noqa: E402

CARPETAS = locales()
IDS = [d.name for d in CARPETAS]


def _comun(nombre: str):
    sys.path.insert(0, str(COMUN))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


terminal = _comun("terminal")
servidor = _comun("servidor")
menu = _comun("menu")
menu_pagina = _comun("menu_pagina")


def _esperar(condicion, limite: float = 8.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return condicion()


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _murio(proceso: subprocess.Popen) -> bool:
    """Si el proceso ya no corre, RECOGIENDOLO de paso.

    `os.kill(pid, 0)` no sirve aqui: un hijo muerto que nadie ha recogido sigue en la
    tabla como zombi y esa pregunta contesta que si. En la cadena de verdad el trampolin
    cuelga de `login`, no del menu, asi que esto es solo una cautela de la prueba -- pero
    sin ella la prueba falla por su propia forma de mirar y no por lo que mide.
    """
    return proceso.poll() is not None


# ------------------------------------------------ 1. las ventanas que no se cerraron


posix = pytest.mark.skipif(os.name == "nt",
                           reason="usa senales POSIX; ver test_windows_aplicaciones.py")


@pytest.fixture
def ventana_atascada(tmp_path):
    """Un proceso que imita a una ventana parada en el `read` del trampolin.

    Lo unico que el barrido puede mirar es la linea de ordenes, asi que lo unico que
    tiene que ser fiel es el NOMBRE del guion: `chec-<etiqueta>-<huella>-ventana.sh` en
    la carpeta temporal. Se le da un `read` de verdad -- no un `sleep` -- porque es
    exactamente lo que deja la ventana viva para siempre y lo que un `SIGTERM` tiene que
    poder atravesar.
    """
    nacidos: list[subprocess.Popen] = []

    def abrir(etiqueta: str = "clima") -> subprocess.Popen:
        guion = Path(terminal._carpeta_temporal()) / f"chec-{etiqueta}-prueba-ventana.sh"
        guion.write_text("#!/bin/sh\nread -r _\n", encoding="utf-8")
        guion.chmod(0o755)
        proceso = subprocess.Popen(["/bin/sh", str(guion)],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        nacidos.append(proceso)
        assert _esperar(lambda: _vivo(proceso.pid), 3.0)
        return proceso

    yield abrir

    for proceso in nacidos:
        try:
            os.kill(proceso.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    for sobra in Path(terminal._carpeta_temporal()).glob("chec-*-prueba-ventana.sh"):
        sobra.unlink(missing_ok=True)


@posix
def test_una_ventana_parada_en_el_read_se_cierra_con_el_barrido(ventana_atascada):
    """El caso que motiva todo esto.

    Una aplicacion que no arranca -- porque otra cosa tiene su puerto -- sale con codigo
    2, el trampolin se para a que lo lean y la ventana se queda. No tiene puerto, asi que
    el apagado por puertos no la ve. Sin barrido no hay nada que la cierre.
    """
    proceso = ventana_atascada()

    cerradas = terminal.cerrar_ventanas()

    assert proceso.pid in cerradas
    assert _esperar(lambda: _murio(proceso)), "la ventana sigue viva"


@posix
def test_el_barrido_no_toca_la_ventana_desde_la_que_se_llama(monkeypatch, tmp_path):
    """La ventana del menu es una ventana como las otras, y es la que esta llamando.

    Barrerla aqui mataria al menu antes de que pudiera contestarle a la pagina que
    apago lo demas -- y antes de cerrar sus propios puertos. Se cierra sola, despues,
    por el mismo camino que las demas: su comando termina bien.
    """
    yo = os.getpid()
    padres = terminal._ascendencia(yo)
    assert padres, "sin ascendencia no hay nada que excluir y la prueba no mide nada"

    # Se le hace creer al barrido que un ancestro real de esta prueba es una ventana
    # nuestra. Si no lo excluyera, se suicidaria la suite.
    ancestro = padres[0]
    monkeypatch.setattr(terminal, "_procesos_en_ventana",
                        lambda tabla=None: [ancestro, yo])

    assert terminal.cerrar_ventanas() == []
    assert _vivo(yo) and _vivo(ancestro)


@posix
def test_el_barrido_solo_mira_los_guiones_que_escribe_este_modulo(ventana_atascada):
    """Un proceso ajeno con un `read` colgado no es asunto del menu.

    El criterio es el nombre del trampolin, que este modulo escribe y nadie mas usa.
    Barrer por cualquier otra cosa -- el nombre del comando, la tty -- seria matar
    procesos de alguien por parecerse a los nuestros.
    """
    ajeno = subprocess.Popen(["/bin/sh", "-c", "read -r _"], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    try:
        nuestra = ventana_atascada()

        cerradas = terminal.cerrar_ventanas()

        assert nuestra.pid in cerradas
        assert ajeno.pid not in cerradas
        assert _vivo(ajeno.pid), "el barrido se llevo por delante un proceso ajeno"
    finally:
        ajeno.kill()
        ajeno.wait(timeout=5)


def test_nombrar_un_trampolin_no_convierte_a_nadie_en_ventana():
    """Hablar de un trampolin no es correrlo, y esto se vio en vivo.

    Al comprobar el barrido a mano, el propio `ps -eo command= | grep chec-...-ventana.sh`
    salia en la lista: su linea de ordenes lleva el patron entero. Con el criterio flojo
    -- solo el nombre -- el barrido le habria mandado un `SIGTERM` a la terminal desde la
    que se estaba mirando. Lo que separa "corre esto" de "habla de esto" es la carpeta:
    un trampolin de verdad vive en la carpeta temporal de este modulo.
    """
    temporal = str(terminal._carpeta_temporal()).rstrip("/")
    assert terminal._es_una_ventana_nuestra(f"/bin/sh {temporal}/chec-clima-a1-ventana.sh")
    assert not terminal._es_una_ventana_nuestra("grep chec-clima-a1-ventana.sh")
    assert not terminal._es_una_ventana_nuestra(
        "/bin/sh /Users/alguien/copias/chec-clima-a1-ventana.sh"), (
        "un guion con ese nombre fuera de la carpeta temporal no lo escribio este modulo")


def test_apagar_todo_barre_las_ventanas_al_final(monkeypatch):
    """El barrido va DESPUES de cerrar las aplicaciones, no antes.

    Antes seria cerrar la ventana de una aplicacion que todavia esta soltando su puerto
    -- y en el simulador, sus kernels --, que es como se queda un proceso de 700 MB
    huerfano. Cada aplicacion se cierra por su puerta y su ventana se va sola; lo que el
    barrido recoge es solo lo que no tenia puerta.
    """
    orden: list[str] = []
    control = menu.Control()
    for app in control.apps.values():
        app.fase = "detenida"

    monkeypatch.setattr(menu, "_apagar_aplicacion",
                        lambda app: orden.append(f"apagar:{app.clave}") or True)
    monkeypatch.setattr(menu._terminal, "cerrar_ventanas",
                        lambda: orden.append("barrer") or [])

    control.apagar_todo()

    assert orden[-1] == "barrer", f"el barrido no fue el ultimo paso: {orden}"
    assert len([p for p in orden if p.startswith("apagar:")]) == 5


# ------------------------------------------- 2. las pestanias que quedaban en pantalla


def _guion_del_menu() -> str:
    return menu_pagina._GUION


def test_la_pestania_que_abre_el_menu_se_guarda_para_poder_cerrarla():
    """Una ventana que abrio un script SI la puede cerrar un script -- y solo esa.

    El permiso viaja en el objeto que devuelve `window.open`. Guardarlo en una variable
    local lo tira en cuanto acaba el manejador del clic, y entonces no queda ninguna
    manera de cerrar la pestania: ni la pagina del menu ni el servidor pueden.
    """
    guion = _guion_del_menu()
    assert "PESTANIAS" in guion, (
        "el menu no guarda las pestanias que abre, asi que no puede cerrarlas despues")
    assert re.search(r"PESTANIAS\[[^\]]+\]\s*=", guion), (
        "PESTANIAS existe pero nunca se le asigna la pestania recien abierta")


def test_cerrar_todo_cierra_las_pestanias_de_los_tableros():
    """«Cerrar todo» apagaba los cinco servidores y dejaba las cinco pestanias abiertas
    sobre tableros muertos. Cerrar el proceso y dejar su ventana es medio apagado."""
    guion = _guion_del_menu()
    cuerpo = re.search(r"function cerrarTodo\(\)[\s\S]*?\n}", guion)
    assert cuerpo, "no se encontro cerrarTodo en la pagina del menu"
    assert "cerrarPestanias" in cuerpo.group(0), (
        "cerrarTodo no cierra las pestanias que el menu abrio")


def test_detener_una_aplicacion_cierra_solo_su_pestania():
    """El boton «Detener» de una tarjeta apaga ESA aplicacion. Su pestania es parte de
    ella; las de las otras cuatro no son asunto suyo."""
    guion = _guion_del_menu()
    assert re.search(r"function cerrarPestania\(", guion), (
        "no hay manera de cerrar la pestania de una sola aplicacion")
    detener = re.search(r"mandar\('detener', app\.clave[^)]*\)", guion)
    assert detener, "no se encontro la llamada de Detener"


def test_cerrar_una_pestania_no_revienta_si_el_navegador_lo_impide():
    """`window.close()` no siempre puede: una pestania duplicada a mano ya no la abrio
    ningun script. Que falle una no puede dejar sin cerrar las otras cuatro ni tumbar el
    apagado a mitad."""
    guion = _guion_del_menu()
    cuerpo = re.search(r"function cerrarPestania\([\s\S]*?\n}", guion)
    assert cuerpo and "try" in cuerpo.group(0) and "catch" in cuerpo.group(0), (
        "cerrar una pestania no esta protegido, y un fallo corta el apagado")


# -------------------------------------- 3. el doble clic sobre un menu ya abierto


class _MenuDeMentira:
    """Un servidor que contesta `/estado` como el menu de verdad, en otra carpeta.

    Es exactamente la situacion que rompia el doble clic: el menu ESTA corriendo, pero
    desde otro clon del repositorio, asi que la comparacion por ruta no lo reconoce.
    """

    def __init__(self, cuerpo: bytes = None):
        self.cuerpo = cuerpo if cuerpo is not None else json.dumps(
            [{"clave": "clima", "titulo": "x", "descripcion": "", "puerto": 8801,
              "url": "", "fase": "detenida", "detalle": "", "instalada": True,
              "construida": True}]).encode("utf-8")
        cuerpo_fijo = self.cuerpo

        class Manejador(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                if self.path != "/estado":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(cuerpo_fijo)))
                self.end_headers()
                self.wfile.write(cuerpo_fijo)

            def log_message(self, *a):
                pass

        class Servidor(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.puerto = s.getsockname()[1]
        self.servidor = Servidor(("127.0.0.1", self.puerto), Manejador)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def cerrar(self):
        self.servidor.shutdown()
        self.servidor.server_close()


@pytest.fixture
def menu_de_mentira():
    abiertos = []

    def abrir(cuerpo=None):
        m = _MenuDeMentira(cuerpo)
        abiertos.append(m)
        return m

    yield abrir
    for m in abiertos:
        m.cerrar()


def test_un_menu_ya_abierto_en_otra_copia_abre_el_navegador_y_no_una_ventana_de_error(
        menu_de_mentira, tmp_path, monkeypatch):
    """El doble clic es "abreme esto", tambien cuando el menu vivo salio de otro clon.

    Antes se decidia por la RUTA de la carpeta contra la linea de ordenes del proceso.
    Dos copias son dos rutas, asi que el menu abierto salia como "algo que no es
    CriticidadCHEC": exit 2, ventana de error, y una ventana atascada mas por intento.
    """
    vivo = menu_de_mentira()
    abiertas: list[str] = []
    monkeypatch.setattr(servidor, "abrir_navegador",
                        lambda url: abiertas.append(url) or True)

    codigo = servidor.revisar_puerto(tmp_path, vivo.puerto, abrir=True,
                                     titulo="CriticidadCHEC",
                                     identificar=menu.es_un_menu)

    assert codigo == 0, "un menu ya abierto no puede mandar al usuario a un error"
    assert abiertas == [f"http://127.0.0.1:{vivo.puerto}/"]


def test_un_extranio_en_el_puerto_del_menu_sigue_saliendo_con_error(tmp_path,
                                                                   monkeypatch):
    """La otra mitad de la regla. Levantar el menu sobre un puerto ajeno serviria un
    tablero de otro en la URL que el usuario tiene en el marcador."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(5)
        puerto = s.getsockname()[1]
        monkeypatch.setattr(servidor, "abrir_navegador", lambda url: True)

        codigo = servidor.revisar_puerto(tmp_path, puerto, abrir=True,
                                         titulo="CriticidadCHEC",
                                         identificar=menu.es_un_menu)

    assert codigo == servidor.SALIDA_PUERTO_AJENO


def test_identificar_al_menu_no_le_pide_la_pagina_a_nadie(menu_de_mentira):
    """`/estado` y no `/`. La pregunta se le hace a un puerto que puede tener cualquier
    cosa detras, y en este proyecto pedirle `/` a la cosa equivocada -- Voila -- cuesta
    un kernel de 700 MB."""
    vivo = menu_de_mentira()
    assert menu.es_un_menu(vivo.puerto) is True


def test_lo_que_no_es_un_menu_no_se_confunde_con_uno(menu_de_mentira):
    """Cualquier servidor puede contestar 200 en `/estado`. Lo que identifica al menu es
    la FORMA de lo que devuelve, no que devuelva algo."""
    otro = menu_de_mentira(b'{"esto": "no es el menu"}')
    assert menu.es_un_menu(otro.puerto) is False


def test_un_puerto_sin_nadie_no_es_un_menu():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    assert menu.es_un_menu(puerto) is False


# ---------------------------------------- 4. el doble clic no tiene donde equivocarse


@pytest.mark.parametrize("carpeta", CARPETAS, ids=IDS)
def test_ninguna_aplicacion_deja_un_senuelo_de_doble_clic(carpeta):
    """No puede haber, al lado de `Iniciar.app`, un archivo que se llame como el.

    `iniciar.command` estaba ahi para lanzarlo A MANO desde una terminal, y su cabecera
    lo explicaba. Daba igual: se llama `iniciar`, esta junto a `Iniciar.app`, y el doble
    clic cae ahi. Con Ghostty reclamando `.command` con rol de EDITOR -- comprobado con
    `lsregister` en la maquina del usuario --, ese doble clic no ejecuta nada: abre el
    archivo en un editor. El arreglo no cabe dentro del guion, porque el guion no llega a
    correr. Solo cabe en el nombre.
    """
    senuelos = [a.name for a in carpeta.iterdir()
                if a.is_file() and a.name.lower().startswith("iniciar")
                and a.suffix in (".command", ".sh", ".tool")]
    assert not senuelos, (
        f"{carpeta.name} trae {senuelos} al lado de Iniciar.app: el doble clic va a caer "
        "ahi y con Ghostty instalado no ejecuta nada")


@pytest.mark.parametrize("carpeta", CARPETAS, ids=IDS)
def test_cada_aplicacion_conserva_como_lanzarla_desde_una_terminal(carpeta):
    """Quitar el senuelo no puede quitar el camino de Linux ni el de una terminal ya
    abierta. Solo cambia de nombre, para que nadie lo confunda con el doble clic."""
    assert (carpeta / "abrir-en-terminal.command").exists(), (
        f"{carpeta.name} se quedo sin manera de lanzarse desde una terminal")
