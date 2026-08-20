"""Doble clic sobre una aplicacion que YA esta abierta.

## Lo que pasaba, medido en esta maquina

Cada aplicacion pide EL SUYO de los puertos del contrato, y `puerto_libre` caia a
un puerto que asignara el sistema cuando el suyo estuviera tomado. Esa caida existe
para que la aplicacion arranque igual si algo ajeno ocupa su puerto, pero convierte
el segundo doble clic en algo peor que un error:

    primer doble clic  -> 01_clima servido en 8801
    segundo doble clic -> 01_clima servido en 53745

Dos copias del MISMO tablero, la segunda en una URL que nadie conoce, invisible
para CriticidadCHEC -- que busca las aplicaciones donde dice el contrato -- y con su
propia ventana de terminal encima. Y con el menu es peor todavia: el puerto 8800 no
se puede reusar, asi que el segundo arranque muere con un `OSError` y deja la
ventana abierta sobre una traza de Python esperando un Intro.

## Lo que tiene que pasar

El doble clic es "abreme esto", no "levanta otra copia". Si el puerto de la
aplicacion ya lo tiene ESA aplicacion, se abre el navegador sobre la que ya esta y
se sale con codigo 0, que es lo que hace que la ventana nueva se cierre sola. Si lo
tiene algo AJENO se sale con error, porque ahi si hay algo que decidir y el mensaje
tiene que quedarse en pantalla.

Nunca se levanta una segunda copia en un puerto al azar.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APPS = RAIZ / "aplicaciones"
COMUN = APPS / "_comun"

sys.path.insert(0, str(COMUN))

import servidor  # noqa: E402


def _puerto_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tomado(puerto: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.6):
            return True
    except OSError:
        return False


def _esperar(condicion, limite: float = 10.0) -> bool:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limite:
        if condicion():
            return True
        time.sleep(0.15)
    return False


# ---------------------------------------------------------------- la decision sola


@pytest.fixture
def app_falsa(tmp_path):
    carpeta = tmp_path / "01_clima"
    carpeta.mkdir()
    return carpeta


def test_un_puerto_libre_deja_seguir(monkeypatch, app_falsa):
    # Se parchea `estado_del_puerto`, que es lo que `revisar_puerto` consulta, y no
    # `puerto_tomado`. Los dos surten efecto -- `estado_del_puerto` llama al segundo --,
    # pero `puerto_tomado` cubre solo el PRIMERO de los dos sondeos: cuando dice que no
    # hay nadie escuchando, `estado_del_puerto` intenta ademas un `bind` DE VERDAD sobre
    # el 8801. Con el tablero de clima levantado, ese bind falla y el puerto sale
    # `TOMADO` con el parche puesto. La prueba pasaba a pasar o fallar segun lo que
    # estuviera corriendo en la maquina.
    monkeypatch.setattr(servidor, "estado_del_puerto", lambda *_a, **_k: servidor.LIBRE)
    assert servidor.revisar_puerto(app_falsa, 8801, abrir=True, titulo="x") is None


def test_su_propio_puerto_ocupado_abre_la_que_ya_esta_y_sale_bien(monkeypatch, app_falsa):
    """Codigo 0 a proposito: es lo que cierra sola la ventana que acaba de abrirse."""
    abiertas = []
    monkeypatch.setattr(servidor, "estado_del_puerto", lambda *_a, **_k: servidor.TOMADO)
    monkeypatch.setattr(servidor, "pid_de", lambda _c: 4321)
    monkeypatch.setattr(servidor, "abrir_navegador", lambda url: abiertas.append(url) or True)

    assert servidor.revisar_puerto(app_falsa, 8801, abrir=True, titulo="Clima") == 0
    assert abiertas == ["http://127.0.0.1:8801/"]


def test_no_abre_el_navegador_si_no_se_lo_pidieron(monkeypatch, app_falsa):
    abiertas = []
    monkeypatch.setattr(servidor, "estado_del_puerto", lambda *_a, **_k: servidor.TOMADO)
    monkeypatch.setattr(servidor, "pid_de", lambda _c: 4321)
    monkeypatch.setattr(servidor, "abrir_navegador", lambda url: abiertas.append(url) or True)

    assert servidor.revisar_puerto(app_falsa, 8801, abrir=False, titulo="Clima") == 0
    assert abiertas == []


def test_un_puerto_ajeno_sale_con_error(monkeypatch, app_falsa, capsys):
    """Aqui si hay algo que decidir, asi que el codigo distinto de cero es lo que
    deja el mensaje en pantalla: la ventana no se cierra sobre el."""
    monkeypatch.setattr(servidor, "estado_del_puerto", lambda *_a, **_k: servidor.TOMADO)
    monkeypatch.setattr(servidor, "pid_de", lambda _c: None)

    codigo = servidor.revisar_puerto(app_falsa, 8801, abrir=True, titulo="Clima")

    assert codigo not in (None, 0)
    salida = capsys.readouterr().out
    assert "8801" in salida
    # La orden que dice QUIEN lo tiene: sin ella el usuario no tiene por donde empezar.
    assert "lsof" in salida or "netstat" in salida


# --------------------------------------------------------------- el archivo de pid


def test_sin_archivo_no_hay_pid(app_falsa):
    assert servidor.pid_de(app_falsa) is None


def test_un_pid_que_ya_no_existe_no_cuenta(app_falsa):
    """El sistema reasigna los pid: fiarse de un archivo olvidado es como se le manda
    una senal a un proceso ajeno."""
    (app_falsa / servidor.ARCHIVO_PID).write_text("999999", encoding="utf-8")
    assert servidor.pid_de(app_falsa) is None


@pytest.mark.xfail(
    os.name == "nt", strict=True,
    reason="en Windows `pid_de` solo compara el NOMBRE DE IMAGEN: `tasklist` no da la "
           "linea de ordenes, asi que otro python cualquiera pasa el filtro. Esta "
           "escrito como limitacion aceptada en el propio `servidor.pid_de`, que la "
           "prefiere a la alternativa -- PowerShell, medio segundo por llamada, cada "
           "2,5 s por aplicacion. Y esta prueba lanza precisamente otro python. "
           "`strict` a proposito: si algun dia se refuerza, esto avisa en vez de "
           "quedarse callado")
def test_un_pid_de_otro_proceso_no_cuenta(app_falsa):
    """Vivo pero no es esta aplicacion: la linea de ordenes no la nombra."""
    ajeno = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (app_falsa / servidor.ARCHIVO_PID).write_text(str(ajeno.pid), encoding="utf-8")
        assert servidor.pid_de(app_falsa) is None
    finally:
        ajeno.kill()
        ajeno.wait(timeout=5)


def test_basura_en_el_archivo_no_revienta(app_falsa):
    (app_falsa / servidor.ARCHIVO_PID).write_text("no soy un numero", encoding="utf-8")
    assert servidor.pid_de(app_falsa) is None


# ------------------------------------------------------- de punta a punta, de verdad


_VISOR = """
import pathlib, sys
sys.path.insert(0, {comun!r})
import servidor
raise SystemExit(servidor.servir(
    pathlib.Path(sys.argv[1]), app=pathlib.Path(sys.argv[2]),
    abrir=False, puerto=int(sys.argv[3])) or 0)
"""


# Las dos pruebas que levantan un tablero DE VERDAD se quedan en POSIX, y por tres
# motivos distintos que se acumulan -- ninguno de ellos un defecto del producto:
#
#   1. La limpieza del fixture manda `os.killpg(os.getpgid(...))`, y en Windows no
#      existe ninguna de las dos: no hay grupos de procesos que senalar. Sin limpieza,
#      cada corrida dejaria servidores vivos.
#   2. La comprobacion de que el segundo arranque no se quedo con otro puerto usa
#      `lsof`, que alli no esta.
#   3. Y `pid_de(carpeta) == proceso.pid` no se sostiene: `.venv\\Scripts\\python.exe`
#      es un REDIRECTOR, y el interprete de verdad corre como hijo suyo. Medido el
#      2026-08-20: `Popen.pid` 2832, `os.getpid()` dentro 4900. El archivo de pid trae
#      el correcto -- el del interprete --, asi que quien esta mal es la comparacion.
#      El menu no se ve afectado porque mata con `taskkill /T`, que recorre el arbol.
#
# Lo que estas dos fijan -- el segundo arranque se rinde, el pid se escribe y se borra
# -- lo cubre en Windows el camino de `revisar_puerto`, que si se prueba arriba.
solo_posix = pytest.mark.skipif(
    os.name == "nt",
    reason="levanta servidores de verdad y los limpia con os.killpg/lsof, que en "
           "Windows no existen; y Popen.pid alli es el shim del venv, no el interprete")


@pytest.fixture
def visor(tmp_path):
    """Un tablero de verdad -- `servidor.servir` sin dobles -- y su limpieza."""
    guion = tmp_path / "visor.py"
    guion.write_text(_VISOR.format(comun=str(COMUN)), encoding="utf-8")
    panel = tmp_path / "panel"
    panel.mkdir()
    (panel / "index.html").write_text("<html><body>x</body></html>", encoding="utf-8")
    carpeta = tmp_path / "01_clima"
    carpeta.mkdir()
    nacidos: list[subprocess.Popen] = []

    def levantar(puerto: int) -> subprocess.Popen:
        proceso = subprocess.Popen(
            [sys.executable, str(guion), str(panel), str(carpeta), str(puerto)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True)
        nacidos.append(proceso)
        return proceso

    yield levantar, carpeta

    for proceso in nacidos:
        try:
            os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


@solo_posix
def test_el_segundo_arranque_no_levanta_una_segunda_copia(visor):
    """El defecto medido: el segundo doble clic servia el mismo tablero en un puerto
    al azar. Ahora se rinde y deja al primero en el suyo."""
    levantar, _carpeta = visor
    puerto = _puerto_libre()
    primero = levantar(puerto)
    assert _esperar(lambda: _tomado(puerto)), "el primero no llego a servir"

    segundo = levantar(puerto)
    segundo.wait(timeout=30)

    assert segundo.returncode == 0, segundo.stdout.read() if segundo.stdout else ""
    # Y no se quedo con ningun otro puerto por el camino.
    escuchando = subprocess.run(
        ["lsof", "-p", str(segundo.pid), "-a", "-iTCP", "-sTCP:LISTEN", "-P"],
        capture_output=True, text=True).stdout
    assert "LISTEN" not in escuchando, escuchando
    assert primero.poll() is None, "el primero se murio, y era el que habia que dejar vivo"


@solo_posix
def test_servir_deja_su_pid_y_lo_borra_al_salir(visor):
    """El archivo es lo que permite reconocer una segunda apertura como propia. Que se
    borre al salir importa igual: uno olvidado apunta tarde o temprano a otro proceso."""
    levantar, carpeta = visor
    puerto = _puerto_libre()
    proceso = levantar(puerto)
    assert _esperar(lambda: _tomado(puerto))

    archivo = carpeta / servidor.ARCHIVO_PID
    assert _esperar(archivo.exists), "no dejo su pid"
    assert servidor.pid_de(carpeta) == proceso.pid

    import urllib.request
    urllib.request.urlopen(
        urllib.request.Request(f"http://127.0.0.1:{puerto}{servidor.RUTA_APAGADO}",
                               method="POST", data=b""), timeout=5).read()
    proceso.wait(timeout=15)

    assert not archivo.exists(), "dejo su pid atras"


# ------------------------------------------------------------ que nadie se lo salte


from ayudas_aplicaciones import locales, visores  # noqa: E402

TODAS = locales()
VISORES = visores()


@pytest.mark.parametrize("app", TODAS, ids=[d.name for d in TODAS])
def test_cada_aplicacion_le_dice_al_servidor_cual_es_su_carpeta(app: Path):
    """Sin su carpeta, nadie sabe donde dejar el pid ni contra que comparar una segunda
    apertura, y la aplicacion vuelve a poder duplicarse en un puerto al azar.

    Los cuatro tableros estaticos la pasan por `servir(app=AQUI)`; el simulador y el
    menu no usan `servir` -- uno levanta Voila y el otro su propio servidor de control
    --, asi que llaman a `revisar_puerto` con ella directamente.
    """
    fuente = (app / "app.py").read_text(encoding="utf-8")
    assert "app=AQUI" in fuente or "revisar_puerto(AQUI" in fuente, (
        f"{app.name}/app.py no le pasa su carpeta: puede duplicarse en otro puerto")


def test_ninguna_aplicacion_cae_a_un_puerto_al_azar():
    """`puerto_libre` cae a un puerto que asigna el sistema cuando el suyo esta tomado.
    Eso es lo que servia la segunda copia en 53745. Con `revisar_puerto` delante ya no
    se llega ahi con el puerto ocupado, y el simulador ni siquiera lo llama."""
    simulador = (APPS / "06_simulador" / "app.py").read_text(encoding="utf-8")
    assert "puerto_libre" not in simulador, (
        "el simulador vuelve a poder levantar un segundo Voila en otro puerto")


def test_el_menu_tambien_se_rinde_si_ya_esta_abierto():
    """El menu no puede caer a otro puerto -- su URL es la que el usuario deja en un
    marcador --, asi que sin esto el segundo arranque moria con un OSError."""
    assert "revisar_puerto" in (COMUN / "menu.py").read_text(encoding="utf-8")
