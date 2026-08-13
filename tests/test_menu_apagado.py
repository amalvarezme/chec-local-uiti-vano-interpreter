"""Apagado de CriticidadCHEC: que cerrar libere el puerto, siempre y por los tres botones.

`test_aplicaciones_locales.py` fija que los DOS EXTREMOS de cada boton coincidan -- que
la ruta que llama el navegador sea la que atiende el servidor, que el puerto del catalogo
sea el del contrato. Eso es estatico: se lee el texto y se comparan cadenas.

Aqui se comprueba lo otro, que ninguna lectura de codigo demuestra: que **el puerto queda
libre de verdad**. Es la unica propiedad que el usuario puede observar, y la unica que
importa para el caso que motiva este archivo -- abrir, cerrar, y volver a abrir. Un
apagado que informa "detenida" y deja el proceso vivo no rompe nada visible en ese
momento: rompe la SIGUIENTE apertura, y ahi ya nadie relaciona el sintoma con el boton
que se pulso antes.

## Por que hay procesos de mentira y no las aplicaciones de verdad

La topologia real son tres procesos encadenados:

    menu.py  --Popen-->  gestor.py  --subprocess.run-->  app.py  --Popen-->  voila

El menu solo tiene en la mano el pid del PRIMERO. Y `gestor.py` usa `subprocess.run`,
que no reenvia senales: una senal al gestor lo mata a el y deja huerfanos a los dos de
abajo, con el puerto tomado por un proceso que ya nadie sabe apagar.

Reproducir esa cadena con las aplicaciones de verdad costaria un entorno de 1,6 GB y
minutos de construccion por prueba. Los dobles de aqui reproducen la TOPOLOGIA -- padre
que espera con `subprocess.run`, hijo que toma el puerto -- que es lo unico de lo que
depende el apagado. Que la cadena real siga teniendo esa forma lo fija
`test_el_gestor_sigue_sin_reenviar_senales_a_la_aplicacion`: si algun dia el gestor
reenvia senales, esa prueba falla y avisa de que estos dobles se quedaron viejos.

El doble del simulador ignora `POST /apagar` y solo se muere con `SIGTERM`, como Voila,
que no tiene ruta de apagado. El doble de los otros cuatro es `servidor.servir` de
verdad: es codigo del repositorio y cuesta milisegundos.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"
COMUN = APPS / "_comun"


def _comun(nombre: str):
    sys.path.insert(0, str(COMUN))
    try:
        return __import__(nombre)
    finally:
        sys.path.pop(0)


menu = _comun("menu")

# Los dobles de aqui se lanzan con `start_new_session` y se rematan con `killpg`, y
# ninguno de los dos existe en Windows. Lo que se mide -- que el puerto quede libre --
# vale igual alli, pero por otro camino (`taskkill /T`), y probarlo pide una maquina
# Windows. Sin esta marca, esta suite no falla por lo que mide sino por el sistema.
pytestmark = pytest.mark.skipif(os.name == "nt",
                                reason="usa grupos de procesos POSIX; ver test_windows_aplicaciones.py")


# --------------------------------------------------------------------------- ayudas


def _puerto_libre() -> int:
    """Un puerto alto que ahora mismo no usa nadie.

    No se reutilizan los puertos del contrato (8800-8866): una prueba que los tomara
    chocaria con el tablero que el usuario tenga abierto -- o peor, se lo apagaria.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tomado(puerto: int) -> bool:
    """Si hay alguien escuchando, sin pedirle ninguna pagina.

    Distinguirlo de `_contesta` importa: al simulador de verdad, pedirle una pagina le
    cuesta un kernel, asi que la prueba que vigila justamente eso no puede usar la otra.
    """
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.6):
            return True
    except OSError:
        return False


def _contesta(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/", timeout=0.6) as r:
            return r.status < 500
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def _esperar(condicion, limite: float = 8.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limite:
        if condicion():
            return True
        time.sleep(0.1)
    return condicion()


def _se_puede_tomar(puerto: int) -> bool:
    """Si el puerto se deja volver a tomar. Es la pregunta que responde si la SIGUIENTE
    apertura va a funcionar, y no es la misma que "ya no contesta": un socket en
    TIME_WAIT no contesta y aun asi rechaza el `bind`."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", puerto))
            return True
        except OSError:
            return False


# El doble de `gestor.py`: espera al hijo con `subprocess.run` y no reenvia nada.
_LANZADOR = """
import subprocess, sys
raise SystemExit(subprocess.run([sys.executable, *sys.argv[1:]]).returncode)
"""

# El doble de un tablero estatico: `servidor.servir` de verdad, con su `POST /apagar`.
_VISOR = """
import pathlib, sys
sys.path.insert(0, {comun!r})
import servidor
servidor.servir(pathlib.Path(sys.argv[1]), abrir=False, puerto=int(sys.argv[2]))
"""

# El doble de Voila: contesta 200 al GET, 404 al `POST /apagar` -- no tiene esa ruta --
# y solo se va con SIGTERM. Escribe su pid donde lo escribe `06_simulador/app.py`, y
# apunta cada GET que le llega: en el Voila de verdad, cada uno cuesta un kernel.
_VOILA = """
import http.server, os, pathlib, socketserver, sys

puerto, archivo_pid = int(sys.argv[1]), pathlib.Path(sys.argv[2])
cuenta = archivo_pid.parent / 'gets.txt'

class Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def do_GET(self):
        with cuenta.open('a', encoding='utf-8') as f:
            f.write(self.path + '\\n')
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')
    def do_POST(self):
        self.send_error(404, 'Voila no tiene ruta de apagado')
    def log_message(self, *a):
        pass

class Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

archivo_pid.write_text(str(os.getpid()), encoding='utf-8')
try:
    with Servidor(('127.0.0.1', puerto), Manejador) as s:
        s.serve_forever()
finally:
    archivo_pid.unlink(missing_ok=True)
"""


@pytest.fixture
def taller(tmp_path):
    """Una fabrica de aplicaciones de mentira, y la limpieza de todo lo que deje viva.

    La limpieza no es cortesia: una prueba que falle a mitad deja un servidor escuchando
    en la maquina de quien corre la suite, y la siguiente prueba lo encuentra ocupado.
    """
    lanzador = tmp_path / "lanzador.py"
    lanzador.write_text(_LANZADOR, encoding="utf-8")
    visor = tmp_path / "visor.py"
    visor.write_text(_VISOR.format(comun=str(COMUN)), encoding="utf-8")
    falso_voila = tmp_path / "voila.py"
    falso_voila.write_text(_VOILA, encoding="utf-8")

    panel = tmp_path / "panel"
    panel.mkdir()
    (panel / "index.html").write_text("<html><body>x</body></html>", encoding="utf-8")

    nacidos: list[subprocess.Popen] = []

    def levantar(clave: str, *, voila: bool, puerto: int, carpeta: Path,
                 encadenado: bool = True) -> menu.Aplicacion:
        """Deja servida una aplicacion de mentira y devuelve la `Aplicacion` del menu.

        `encadenado` reproduce la cadena de tres procesos del menu real. En False el
        proceso servidor es hijo directo, que es lo que pasa cuando alguien abre la
        aplicacion a mano y el menu solo la adopta.
        """
        carpeta.mkdir(parents=True, exist_ok=True)
        if voila:
            orden = [str(falso_voila), str(puerto), str(carpeta / ".servidor.pid")]
        else:
            orden = [str(visor), str(panel), str(puerto)]
        if encadenado:
            orden = [str(lanzador), *orden]

        proceso = subprocess.Popen([sys.executable, *orden],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        nacidos.append(proceso)
        assert _esperar(lambda: _tomado(puerto)), f"{clave} no llego a servir"

        app = menu.Aplicacion(clave, carpeta.name, clave, "doble de prueba", puerto,
                              voila=voila)
        app.carpeta = carpeta
        app.proceso = proceso
        app.fase = "corriendo"
        return app

    yield levantar

    for proceso in nacidos:
        try:
            os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


# ------------------------------------------------------- lo que el usuario observa


def test_detener_un_visor_lanzado_por_el_menu_libera_su_puerto(taller, tmp_path):
    """El caso facil, y el unico que hoy funciona entero: el tablero tiene su propia
    puerta (`POST /apagar`) y sale por ella."""
    puerto = _puerto_libre()
    app = taller("clima", voila=False, puerto=puerto, carpeta=tmp_path / "01_clima")

    menu._apagar_aplicacion(app)

    assert _esperar(lambda: not _contesta(puerto)), "el visor sigue contestando"
    assert _se_puede_tomar(puerto)


def test_detener_el_simulador_lanzado_por_el_menu_libera_su_puerto(taller, tmp_path):
    """El simulador no tiene ruta de apagado, asi que el menu tiene que llegar a el por
    senales. Y el pid que el menu guarda no es el suyo: es el del gestor, dos procesos
    mas arriba. Matar solo a ese deja a Voila huerfano CON EL PUERTO TOMADO, y el menu
    informando de que lo cerro."""
    puerto = _puerto_libre()
    app = taller("simulador", voila=True, puerto=puerto,
                 carpeta=tmp_path / "06_simulador")

    menu._apagar_aplicacion(app)

    assert _esperar(lambda: not _contesta(puerto)), (
        "el simulador sigue sirviendo: se mato al gestor y el que tiene el puerto "
        "quedo huerfano")
    assert _se_puede_tomar(puerto)


def test_detener_una_aplicacion_que_el_menu_no_lanzo_libera_su_puerto(taller, tmp_path):
    """El menu adopta lo que ya este servido en el puerto -- para eso los comparte con
    los comandos `/app-local-*`. Adoptada, `app.proceso` es None; si el apagado depende
    de tener el proceso en la mano, el boton no hace nada y aun asi dice que si."""
    puerto = _puerto_libre()
    app = taller("simulador", voila=True, puerto=puerto,
                 carpeta=tmp_path / "06_simulador", encadenado=False)
    app.proceso = None                      # como lo deja `abrir()` al adoptarla
    app.detalle = "ya estaba abierta"

    menu._apagar_aplicacion(app)

    assert _esperar(lambda: not _contesta(puerto)), (
        "el simulador abierto a mano sobrevivio al apagado del menu")
    assert _se_puede_tomar(puerto)


def test_detener_no_dice_detenida_si_el_puerto_sigue_ocupado(taller, tmp_path):
    """Una aplicacion que no cede -- o un proceso ajeno que tomo ese puerto -- tiene que
    salir como fallo, no como detenida.

    Mentir aqui es peor que fallar: el menu ofrece "Abrir", el usuario pulsa, el menu ve
    que el puerto contesta y lo adopta como si acabara de arrancarlo. El tablero que sale
    es el viejo, y nada en la pantalla lo dice.

    El contrato ademas prohibe matar en ese puerto un proceso que el menu no lanzo, asi
    que informar es lo unico que queda por hacer."""
    puerto = _puerto_libre()
    intruso = taller("intruso", voila=True, puerto=puerto,
                     carpeta=tmp_path / "intruso", encadenado=False)
    app = menu.Aplicacion("clima", "01_clima", "Nube por vano", "", puerto)
    app.carpeta = tmp_path / "01_clima"
    app.carpeta.mkdir()
    app.fase = "corriendo"                  # adoptada: sin proceso y sin pid en disco

    control = menu.Control()
    control.apps["clima"] = app
    estado = control.detener("clima")

    assert _contesta(puerto), "el doble se apago solo; la prueba no comprueba nada"
    assert estado["fase"] == "fallo", (
        f"dijo '{estado['fase']}' con el puerto {puerto} todavia sirviendo")
    assert str(puerto) in estado["detalle"] or "puerto" in estado["detalle"], (
        "el detalle tiene que nombrar el puerto: es lo unico accionable")
    assert intruso.proceso.poll() is None, "mato un proceso que el menu no lanzo"


def test_apagar_todo_no_deja_ningun_puerto_ocupado(taller, tmp_path):
    """El boton que mas promete de los tres. Lo pulsa gente que se va: si deja algo vivo,
    nadie va a volver a mirarlo."""
    puertos = {"clima": _puerto_libre(), "simulador": _puerto_libre()}
    control = menu.Control()
    control.apps = {
        "clima": taller("clima", voila=False, puerto=puertos["clima"],
                        carpeta=tmp_path / "01_clima"),
        "simulador": taller("simulador", voila=True, puerto=puertos["simulador"],
                            carpeta=tmp_path / "06_simulador"),
    }

    control.apagar_todo()

    for clave, puerto in puertos.items():
        assert _esperar(lambda p=puerto: not _contesta(p)), f"{clave} sigue vivo"
        assert _se_puede_tomar(puerto), f"{clave} dejo el puerto {puerto} sin poder tomar"
    assert all(a.fase == "detenida" for a in control.apps.values())


@pytest.mark.parametrize("voila", [False, True], ids=["visor", "simulador"])
def test_abrir_y_cerrar_el_mismo_puerto_tres_veces_seguidas(taller, tmp_path, voila):
    """El uso repetido, que es donde aparecen los puertos bloqueados.

    Tres vueltas y no dos: la primera no distingue nada, la segunda descubre el socket
    que quedo en TIME_WAIT, y la tercera descubre al huerfano que sobrevivio a la segunda
    -- que es el fallo que no se ve hasta que se insiste.
    """
    puerto = _puerto_libre()
    carpeta = tmp_path / ("06_simulador" if voila else "01_clima")
    for vuelta in range(1, 4):
        app = taller(f"vuelta{vuelta}", voila=voila, puerto=puerto, carpeta=carpeta)
        menu._apagar_aplicacion(app)
        assert _esperar(lambda: not _contesta(puerto)), f"vuelta {vuelta}: sigue vivo"
        assert _se_puede_tomar(puerto), f"vuelta {vuelta}: el puerto quedo bloqueado"


def test_el_menu_se_apaga_por_su_ruta_y_devuelve_su_puerto(tmp_path):
    """El "Cerrar todo" de la pagina del menu y el de la barra de los tableros llegan los
    dos al mismo `POST /apagar-todo`. Aqui se comprueba el extremo que atiende: que la
    peticion conteste, que el proceso del menu SALGA, y que su puerto se pueda volver a
    tomar en el acto -- que es lo que hace falta para reabrirlo sin esperar."""
    puerto = _puerto_libre()
    guion = tmp_path / "menu_de_prueba.py"
    guion.write_text(
        f"import sys\nsys.path.insert(0, {str(COMUN)!r})\n"
        f"import menu\nraise SystemExit(menu.servir_menu(abrir=False, puerto={puerto}))\n",
        encoding="utf-8")
    proceso = subprocess.Popen([sys.executable, str(guion)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        assert _esperar(lambda: _contesta(puerto)), "el menu no llego a servir"

        peticion = urllib.request.Request(
            f"http://127.0.0.1:{puerto}/apagar-todo", method="POST", data=b"")
        # La respuesta llega DESPUES de haber apagado, no antes: es lo que deja que la
        # pagina distinga "cerrado todo" de "quedo algo vivo en tal puerto".
        respuesta = json.loads(urllib.request.urlopen(peticion, timeout=60).read())
        assert respuesta == {"cerrado": True, "vivas": []}

        assert _esperar(lambda: proceso.poll() is not None), "el menu no salio"
        assert proceso.returncode == 0, "el menu salio con error al cerrarse"
        assert _se_puede_tomar(puerto), "el puerto del menu quedo bloqueado"
    finally:
        if proceso.poll() is None:
            os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
            proceso.wait(timeout=5)


def test_vigilar_el_simulador_no_le_pide_ni_una_pagina(taller, tmp_path):
    """El sondeo de salud del menu no puede ser un `GET /` sobre el simulador.

    Voila RENDERIZA el cuaderno en cada peticion: cada comprobacion deja atras un kernel
    con PyTorch dentro, ~700 MB, que no se recicla hasta tres minutos despues de quedar
    ocioso. Medido sobre el simulador de verdad: preguntarle unas cuantas veces si seguia
    vivo lo llevo de uno a seis kernels vivos a la vez.

    Y el dano no acababa en la memoria. Con la maquina cargada por esos mismos kernels,
    Voila dejaba de contestar dentro del plazo del sondeo, el menu lo daba por muerto,
    y por darlo por muerto no le mandaba la senal de apagado: informaba de que lo habia
    cerrado y lo dejaba sirviendo.

    Lo que hace falta saber es si el PUERTO esta tomado, y eso lo contesta una conexion
    TCP sin pedir ninguna pagina.
    """
    puerto = _puerto_libre()
    carpeta = tmp_path / "06_simulador"
    app = taller("simulador", voila=True, puerto=puerto, carpeta=carpeta,
                 encadenado=False)
    app.proceso = None                          # adoptada, como al abrirla a mano

    control = menu.Control()
    control.apps = {"simulador": app}
    control.abrir("simulador")                  # la reconoce sin lanzar nada
    for _ in range(4):
        control.estado()                        # lo que hace la pagina cada 2,5 s
    menu._apagar_aplicacion(app)

    assert _esperar(lambda: not _tomado(puerto)), "no se apago"
    gets = carpeta / "gets.txt"
    assert not gets.exists(), (
        "el menu le pidio paginas al simulador: "
        f"{gets.read_text(encoding='utf-8').split()} -- cada una es un kernel")


# ------------------------------------------------ que los dobles sigan siendo fieles


def test_el_gestor_sigue_sin_reenviar_senales_a_la_aplicacion():
    """La razon de ser del doble `_LANZADOR`, y de que el apagado tenga que alcanzar a
    los NIETOS del menu.

    `gestor.py` espera a la aplicacion con `subprocess.run`, que no instala ningun
    manejador de senales: un SIGTERM al gestor lo mata a el y deja al que tiene el puerto
    vivo y sin padre. Si algun dia el gestor aprende a reenviar, esta prueba falla, y hay
    que revisar si el apagado por grupo de procesos sigue haciendo falta."""
    codigo = (COMUN / "gestor.py").read_text(encoding="utf-8")
    assert "subprocess.run([str(py), str(ruta), *argumentos])" in codigo
    assert "signal" not in codigo, (
        "el gestor toco senales: los dobles de esta prueba se quedaron viejos")


def test_los_tres_botones_de_cerrar_todo_llaman_a_la_misma_ruta():
    """Hay tres origenes distintos -- la pagina del menu, la barra inyectada en los
    cuatro tableros estaticos, y los widgets del simulador -- y un solo sitio que
    atiende. Los tres tienen la ruta escrita a mano en su propio JavaScript, asi que
    nada salvo esta prueba impide que uno se quede atras."""
    pagina = _comun("menu_pagina").pagina()
    barra = _comun("servidor")._BARRA_MENU
    preparar = (APPS / "06_simulador" / "preparar.py").read_text(encoding="utf-8")

    assert "fetch('/apagar-todo', { method: 'POST' })" in pagina
    assert "sendBeacon(MENU + 'apagar-todo'" in barra
    assert 'sendBeacon("__MENU__" + "apagar-todo"' in preparar

    # Y el extremo que atiende, en el unico sitio donde esta escrito.
    assert '"/apagar-todo"' in (COMUN / "menu.py").read_text(encoding="utf-8")


def test_la_url_que_reciben_los_tableros_sale_del_puerto_del_menu():
    """Los cuatro tableros estaticos reciben la URL del menu por `--menu` y el simulador
    por la variable `MENU_CRITICIDAD`. Las dos tienen que salir de `PUERTO_MENU` y no de
    un 8800 escrito a mano: con el numero suelto, arrancar el menu en otro puerto deja a
    los tableros mandando su "Cerrar todo" a un puerto donde ya no hay nadie -- y el
    `sendBeacon` no informa de errores, asi que el usuario ve como no pasa nada."""
    codigo = (COMUN / "menu.py").read_text(encoding="utf-8")
    assert codigo.count('f"http://127.0.0.1:{PUERTO_MENU}/"') == 2, (
        "la URL del menu tiene que derivarse de PUERTO_MENU en los dos sitios que la "
        "reparten: el argumento --menu y la variable MENU_CRITICIDAD")
