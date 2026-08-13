"""Servidor de control de CriticidadCHEC: el menu que gobierna las cinco aplicaciones.

## Que hace, y por que hace falta

Las cinco aplicaciones ya sabian arrancar solas por doble clic. Lo que no habia era un
sitio desde el que verlas todas, saber cual esta viva y apagarlas sin ir a buscar su
ventana de terminal. Este modulo es ese sitio: un servidor de control en un puerto
fijo que **lanza y detiene procesos hijos**, uno por aplicacion, cada uno en su propio
puerto.

## Por que hijos y no hilos

Porque cada aplicacion ya es un proceso con su propio entorno virtual, sus propias
dependencias y su propio servidor. El simulador ademas lanza Voila, que lanza kernels.
Meterlas en el proceso del menu obligaria a que el menu tuviera la union de las cinco
listas de dependencias -- torch incluido, 1,6 GB -- para poder importar cualquiera de
ellas. Asi el menu es biblioteca estandar pura y cada aplicacion sigue aislada.

## Como se apaga un hijo

Por su propia puerta, no a senalazos: un `POST /apagar` a su puerto, que es exactamente
lo que hace su boton de cerrar. Asi el hijo cierra su socket y sale con codigo 0 por el
mismo camino ya probado. `SIGTERM` queda como respaldo para el que no conteste, y
`SIGKILL` para el que ni aun asi se vaya.

El simulador es la excepcion: no lo sirve `servidor.py` sino Voila, que no tiene ruta
de apagado. A ese se le manda `SIGTERM` directamente, que es lo que su propio boton de
cerrar acaba haciendo.
"""
from __future__ import annotations

import http.server
import json
import os
import signal
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entorno  # noqa: E402
import servidor as _servidor  # noqa: E402
from menu_pagina import pagina  # noqa: E402

RAIZ_APPS = Path(__file__).resolve().parents[1]
GESTOR = Path(__file__).resolve().parent / "gestor.py"

# Puerto del menu. Fijo, como los de las aplicaciones: es la URL que el usuario deja
# en un marcador y la que los tableros necesitan para saber a donde volver.
PUERTO_MENU = 8800


class Aplicacion:
    """Una de las cinco aplicaciones gobernadas, y el proceso que la sirve."""

    __slots__ = ("clave", "carpeta", "titulo", "descripcion", "puerto", "voila",
                 "proceso", "fase", "detalle")

    def __init__(self, clave, carpeta, titulo, descripcion, puerto, *, voila=False):
        self.clave = clave
        self.carpeta = RAIZ_APPS / carpeta
        self.titulo = titulo
        self.descripcion = descripcion
        self.puerto = puerto
        self.voila = voila
        self.proceso: subprocess.Popen | None = None
        # `fase` es lo unico que la pagina necesita saber para decidir que dibujar.
        self.fase = "detenida"      # detenida | preparando | corriendo | fallo
        self.detalle = ""

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.puerto}/"

    def instalada(self) -> bool:
        return entorno.existe(self.carpeta)

    def construida(self) -> bool:
        """Si ya tiene su artefacto, arrancar cuesta menos de un segundo."""
        if self.voila:
            return (self.carpeta / "paquete" / "manifiesto.json").exists()
        return (self.carpeta / "panel" / "index.html").exists()

    def viva(self) -> bool:
        return self.proceso is not None and self.proceso.poll() is None


def catalogo() -> dict[str, Aplicacion]:
    """Las cinco aplicaciones, en el orden en que se muestran.

    Los puertos son los mismos que fija `.claude/commands/_contrato-apps-locales.md`,
    para que una aplicacion abierta desde el menu y otra abierta a mano se reconozcan
    entre si en vez de duplicarse en dos puertos distintos.
    """
    return {a.clave: a for a in (
        Aplicacion("clima", "01_clima", "Nube por vano y clima",
                   "La nube por vano sobre el mapa, con las 6 variables, la serie de "
                   "doble eje y los 6 violines.", 8801),
        Aplicacion("agrupamiento", "02_agrupamiento_vanos", "Agrupamiento de vanos",
                   "Agrupamiento por UITI acumulado y numero de eventos.", 8802),
        Aplicacion("trayectorias_circuitos", "03_trayectorias_circuitos",
                   "Trayectorias de circuitos",
                   "Trayectoria y agrupamiento de circuitos con ventana deslizante.",
                   8803),
        Aplicacion("trayectorias_vanos", "04_trayectorias_vanos",
                   "Trayectorias de vanos",
                   "Lo mismo un nivel mas abajo: agrupamiento y evolucion por vano.",
                   8804),
        Aplicacion("simulador", "06_simulador", "Simulador de riesgo por vano",
                   "Que pasaria si: corre el modelo MIL sobre los vanos y valores que "
                   "elijas. Es la unica que necesita Python vivo.", 8866, voila=True),
    )}


class Control:
    """Estado compartido entre el servidor HTTP y los hilos que lanzan aplicaciones."""

    def __init__(self) -> None:
        self.apps = catalogo()
        self.candado = threading.Lock()
        self.apagando = threading.Event()

    # ------------------------------------------------------------------ arranque

    def abrir(self, clave: str) -> dict:
        """Pide que `clave` quede servida. Devuelve el estado en el acto.

        No bloquea: instalar un entorno son minutos y construir un tablero, ~71 s. El
        trabajo va a un hilo y la pagina sigue el avance por `/estado`. Bloquear aqui
        dejaria al navegador esperando una respuesta que nunca llega a tiempo y al
        usuario sin saber si el clic hizo algo.
        """
        app = self.apps[clave]
        with self.candado:
            if app.viva() or app.fase == "preparando":
                return self.estado_de(app)
            # Puede estar servida por alguien que la abrio a mano, fuera del menu.
            if _responde(app.url):
                app.fase, app.detalle = "corriendo", "ya estaba abierta"
                return self.estado_de(app)
            app.fase, app.detalle = "preparando", "arrancando"
        threading.Thread(target=self._preparar, args=(app,), daemon=True).start()
        return self.estado_de(app)

    def _preparar(self, app: Aplicacion) -> None:
        try:
            if not app.instalada():
                app.detalle = "creando el entorno (varios minutos, solo la primera vez)"
                hecho = subprocess.run(
                    [sys.executable, str(GESTOR), "instalar", "--app", str(app.carpeta)],
                    capture_output=True, text=True)
                if hecho.returncode != 0:
                    self._fallo(app, "no se pudo crear el entorno", hecho)
                    return
            if not app.construida():
                app.detalle = "construyendo el tablero (puede tardar un par de minutos)"
            else:
                app.detalle = "levantando el servidor"

            comando = [sys.executable, str(GESTOR), "iniciar",
                       "--app", str(app.carpeta), "--puerto", str(app.puerto),
                       "--no-abrir"]
            if not app.voila:
                comando += ["--menu", f"http://127.0.0.1:{PUERTO_MENU}/"]
            ambiente = dict(os.environ, PYTHONUNBUFFERED="1",
                            MENU_CRITICIDAD=f"http://127.0.0.1:{PUERTO_MENU}/")
            app.proceso = subprocess.Popen(comando, env=ambiente,
                                           stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
            # Construir corre DENTRO de ese proceso, asi que el plazo tiene que cubrir
            # el peor caso medido -- 71 s de cuaderno mas el arranque -- con holgura.
            if _esperar(app.url, limite=600.0, proceso=app.proceso):
                app.fase, app.detalle = "corriendo", ""
            else:
                self._fallo(app, "el servidor no respondio", None)
        except Exception as error:                      # noqa: BLE001
            self._fallo(app, str(error), None)

    def _fallo(self, app: Aplicacion, motivo: str, hecho) -> None:
        app.fase = "fallo"
        # La ultima linea de pip o del constructor es la unica pista util, y el usuario
        # no esta mirando ninguna terminal: el menu es su unica ventana.
        cola = ""
        if hecho is not None:
            lineas = [l for l in (hecho.stderr or hecho.stdout or "").splitlines() if l.strip()]
            cola = f" -- {lineas[-1][:200]}" if lineas else ""
        app.detalle = motivo + cola
        app.proceso = None

    # ------------------------------------------------------------------- apagado

    def detener(self, clave: str) -> dict:
        app = self.apps[clave]
        _apagar_aplicacion(app)
        app.fase, app.detalle = "detenida", ""
        return self.estado_de(app)

    def apagar_todo(self) -> None:
        for app in self.apps.values():
            _apagar_aplicacion(app)
            app.fase, app.detalle = "detenida", ""
        self.apagando.set()

    # -------------------------------------------------------------------- estado

    def estado_de(self, app: Aplicacion) -> dict:
        if app.fase == "corriendo" and not app.viva() and not _responde(app.url):
            # Se cerro por su cuenta: con su propio boton, o con Ctrl+C en su ventana.
            app.fase, app.detalle = "detenida", ""
        return {
            "clave": app.clave, "titulo": app.titulo, "descripcion": app.descripcion,
            "puerto": app.puerto, "url": app.url, "fase": app.fase,
            "detalle": app.detalle, "instalada": app.instalada(),
            "construida": app.construida(),
        }

    def estado(self) -> list[dict]:
        return [self.estado_de(app) for app in self.apps.values()]


# ----------------------------------------------------------------------- ayudas


def _responde(url: str, espera: float = 0.6) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=espera) as respuesta:
            return respuesta.status < 500
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def _esperar(url: str, *, limite: float, proceso: subprocess.Popen | None = None) -> bool:
    """Espera a que `url` conteste. Se rinde antes si el proceso muere."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limite:
        if proceso is not None and proceso.poll() is not None:
            return False
        if _responde(url):
            return True
        time.sleep(0.4)
    return False


def _apagar_aplicacion(app: Aplicacion) -> None:
    """Apaga la aplicacion por su propia puerta y, si no cede, a senales.

    El orden importa. `POST /apagar` la deja salir con codigo 0 cerrando su socket, que
    es el camino ya probado; matarla de entrada dejaria el puerto en TIME_WAIT y, en el
    caso del simulador, kernels de Voila huerfanos.
    """
    if not app.voila and _responde(app.url):
        peticion = urllib.request.Request(
            app.url.rstrip("/") + _servidor.RUTA_APAGADO, method="POST", data=b"")
        try:
            urllib.request.urlopen(peticion, timeout=3).read()
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            pass

    proceso = app.proceso
    if proceso is None:
        return
    for senal, plazo in ((None, 3.0), (signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0)):
        try:
            if senal is not None:
                proceso.send_signal(senal)
            proceso.wait(timeout=plazo)
            app.proceso = None
            return
        except subprocess.TimeoutExpired:
            continue
        except (ProcessLookupError, OSError):
            break
    app.proceso = None


# ------------------------------------------------------------------- servidor


class _Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    control: Control = None       # type: ignore[assignment]
    silencioso = True

    def do_GET(self) -> None:     # noqa: N802 -- nombre impuesto por la clase base
        ruta = self.path.split("?", 1)[0]
        if ruta == "/":
            self._enviar(pagina().encode("utf-8"), "text/html; charset=utf-8")
        elif ruta == "/estado":
            self._json(self.control.estado())
        else:
            self.send_error(404, "No encontrado")

    def do_POST(self) -> None:    # noqa: N802
        # El cuerpo hay que leerlo siempre, aunque no sirva: `sendBeacon` manda uno, y
        # dejarlo en el socket descoloca la siguiente peticion de esa conexion viva.
        largo = int(self.headers.get("Content-Length") or 0)
        if largo:
            self.rfile.read(largo)

        ruta = self.path.split("?", 1)[0]
        if ruta == "/apagar-todo":
            self._enviar(b"cerrando", "text/plain; charset=utf-8")
            # En otro hilo y con un respiro, por lo mismo que en `servidor.py`: apagar
            # desde el hilo que atiende la peticion se bloquea contra si mismo.
            threading.Timer(0.3, self._apagar_todo).start()
            return

        clave = _parametro(self.path, "app")
        if clave not in self.control.apps:
            self.send_error(404, "Esa aplicacion no existe")
            return
        if ruta == "/abrir":
            self._json(self.control.abrir(clave))
        elif ruta == "/detener":
            self._json(self.control.detener(clave))
        else:
            self.send_error(404, "No encontrado")

    def _apagar_todo(self) -> None:
        self.control.apagar_todo()
        self.server.shutdown()

    def _json(self, dato) -> None:
        self._enviar(json.dumps(dato, ensure_ascii=False).encode("utf-8"),
                     "application/json; charset=utf-8")

    def _enviar(self, cuerpo: bytes, tipo: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        # El menu cambia en cada peticion: cachearlo mostraria aplicaciones ya cerradas
        # como si siguieran vivas.
        self.send_header("Cache-Control", "no-store")
        # Los tableros viven en OTRO puerto, o sea otro origen. Esto es lo que deja que
        # su boton "Cerrar todo" llegue hasta aqui.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, formato: str, *args) -> None:
        if not self.silencioso:
            super().log_message(formato, *args)


class _Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _parametro(ruta: str, nombre: str) -> str:
    consulta = ruta.split("?", 1)[1] if "?" in ruta else ""
    return urllib.parse.parse_qs(consulta).get(nombre, [""])[0]


def servir_menu(*, abrir: bool = True, puerto: int | None = None,
                verboso: bool = False) -> int:
    """Levanta el menu y no vuelve hasta que se cierre todo."""
    control = Control()
    manejador = type("Manejador", (_Manejador,), {
        "control": control, "silencioso": not verboso})
    puerto = puerto or PUERTO_MENU

    with _Servidor(("127.0.0.1", puerto), manejador) as servidor_menu:
        url = f"http://127.0.0.1:{puerto}/"
        print(f"\n  CriticidadCHEC en  {url}")
        print("  Deja esta ventana abierta mientras lo usas. Ctrl+C para cerrarlo todo.\n")
        if abrir:
            threading.Timer(0.3, lambda: _servidor.abrir_navegador(url)).start()
        try:
            servidor_menu.serve_forever()
            print("  Cerrado desde el menu.")
        except KeyboardInterrupt:
            print("\n  Cerrando las aplicaciones abiertas...")
            control.apagar_todo()
            print("  Detenido.")
    return 0
