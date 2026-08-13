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
de apagado. A ese se le manda `SIGTERM` al pid que dejo escrito en `.servidor.pid`, que
es exactamente lo que hace su propio boton de cerrar.

## Y por que la senal va al GRUPO, no al proceso

Lo que el menu tiene en la mano no es la aplicacion: es el gestor. La cadena real son
tres o cuatro procesos.

    menu.py  --Popen-->  gestor.py  --subprocess.run-->  app.py  --Popen-->  voila

`subprocess.run` no reenvia senales. Un `SIGTERM` al gestor lo mata a el y deja al de
abajo -- el que tiene el puerto -- vivo y sin padre, con el menu informando de que lo
cerro. Por eso cada hijo se lanza en su propia sesion (`start_new_session`) o grupo de
procesos en Windows: eso convierte "alcanzar a los nietos" en una sola llamada, sin
recorrer la tabla de procesos ni depender de `ps`.

Efecto lateral buscado: `Ctrl+C` en la ventana del menu ya no llega a los hijos por la
terminal, sino que lo reparte `apagar_todo`. Es lo mismo que pasaba antes por accidente
cuando el menu corria en primer plano, y ademas funciona cuando se lanzo en segundo
plano, que es donde antes no pasaba nada.

## Y por que "detenida" solo se dice cuando el puerto esta libre

Un apagado que informa de exito y deja el puerto tomado no rompe nada visible en ese
momento: rompe la siguiente apertura. El menu ve el puerto contestando, lo adopta como
si acabara de arrancarlo, y sirve el tablero VIEJO sin que nada en la pantalla lo diga.
Asi que `_apagar_aplicacion` devuelve si el puerto quedo libre, y quien no lo suelta
sale como fallo con el numero de puerto en el detalle.
"""
from __future__ import annotations

import http.server
import json
import os
import signal
import socket
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

ES_WINDOWS = os.name == "nt"

# Donde `06_simulador/app.py` deja escrito el pid de Voila. El nombre esta ahi y aqui, y
# no en un sitio comun, porque los dos modulos tienen que poder correr sin importarse: el
# menu es biblioteca estandar pura y la aplicacion vive en su propio entorno.
ARCHIVO_PID = ".servidor.pid"

# Cada hijo, en su propia sesion (POSIX) o grupo (Windows). Es lo que despues permite
# alcanzar de una sola llamada al nieto que tiene el puerto. Ver el encabezado.
_AISLAR_GRUPO = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if ES_WINDOWS
                 else {"start_new_session": True})

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
            if _ocupado(app.puerto):
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
                                           stderr=subprocess.DEVNULL,
                                           **_AISLAR_GRUPO)
            # Construir corre DENTRO de ese proceso, asi que el plazo tiene que cubrir
            # el peor caso medido -- 71 s de cuaderno mas el arranque -- con holgura.
            if _esperar(app.puerto, limite=600.0, proceso=app.proceso):
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
        _anotar_apagado(app, _apagar_aplicacion(app))
        return self.estado_de(app)

    def apagar_todo(self) -> list[dict]:
        """Apaga las cinco y devuelve las que no soltaron su puerto.

        Devolver los supervivientes en vez de tragarselos es lo que deja que la pagina
        diga la verdad. El menu se cierra igual -- eso es lo que promete el boton --,
        pero quien lo pulso se entera de que quedo algo vivo y de en que puerto, que es
        justo lo que no se puede averiguar despues de que el menu se haya ido.
        """
        supervivientes = []
        for app in self.apps.values():
            libre = _apagar_aplicacion(app)
            _anotar_apagado(app, libre)
            if not libre:
                supervivientes.append(self.estado_de(app))
        self.apagando.set()
        return supervivientes

    # -------------------------------------------------------------------- estado

    def estado_de(self, app: Aplicacion) -> dict:
        if app.fase == "corriendo" and not app.viva() and not _ocupado(app.puerto):
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


def _ocupado(puerto: int, espera: float = 0.6) -> bool:
    """Si hay alguien escuchando en ese puerto. Se abre una conexion y se cierra.

    Antes esto era un `GET /`, y con el simulador era una calamidad silenciosa: Voila
    RENDERIZA el cuaderno en cada peticion, asi que cada comprobacion de salud dejaba
    atras un kernel de ~700 MB con PyTorch dentro. Medido: preguntarle tres veces si
    estaba vivo lo llevo de uno a seis kernels. Y al cargarse la maquina con lo que el
    propio sondeo iba creando, Voila dejaba de contestar dentro del plazo, el menu lo
    daba por muerto y ni siquiera le mandaba la senal de apagado.

    La pregunta que hace falta no es "que sirve" sino "esta el puerto tomado", que es
    tambien la que responde el `lsof ... -sTCP:LISTEN` del contrato de `/app-local-*`.
    Y esa se contesta con una conexion TCP, que no renderiza nada, no arranca ningun
    kernel y no depende de lo cargada que este la maquina.
    """
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=espera):
            return True
    except OSError:
        return False


def _esperar(puerto: int, *, limite: float, proceso: subprocess.Popen | None = None) -> bool:
    """Espera a que alguien tome el puerto. Se rinde antes si el proceso muere."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < limite:
        if proceso is not None and proceso.poll() is not None:
            return False
        if _ocupado(puerto):
            return True
        time.sleep(0.4)
    return False


def _apagar_aplicacion(app: Aplicacion) -> bool:
    """Apaga la aplicacion y dice si el puerto quedo libre.

    Tres intentos, del mas limpio al mas bruto, y cada uno solo si el anterior no basto:

    1. **Su propia puerta.** `POST /apagar` para los cuatro tableros; `SIGTERM` al pid
       de `.servidor.pid` para el simulador, que no tiene esa ruta. Los dos salen con
       codigo 0 cerrando su socket, y en el simulador ademas apagan sus kernels.
    2. **`SIGTERM` al grupo** de lo que el menu lanzo. Alcanza a los nietos, que es
       donde vive el proceso que tiene el puerto de verdad.
    3. **`SIGKILL` al grupo**, para el que ni con esas.

    Lo que NUNCA hace es matar por puerto. Un proceso ajeno que este en 8801 no es
    asunto del menu -- ese es el mismo criterio del contrato de `/app-local-*` --, asi
    que se informa de que sigue ahi en vez de dispararle.
    """
    if app.proceso is None and not _ocupado(app.puerto):
        return True

    _pedir_por_su_puerta(app)
    if _esperar_a_que_suelte(app):
        return True

    if app.proceso is not None:
        for senal, plazo in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 2.0)):
            _senalar_al_grupo(app.proceso, senal)
            if _esperar_a_que_suelte(app, plazo):
                return True
    return not _ocupado(app.puerto)


def _pedir_por_su_puerta(app: Aplicacion) -> None:
    """El apagado limpio, el mismo que usa el boton de cerrar de cada aplicacion.

    Se llama SIEMPRE, sin comprobar antes si la aplicacion contesta. Comprobarlo era lo
    que dejaba vivo al simulador: bastaba con que Voila tardara en responder -- porque
    estaba arrancando, o porque la maquina iba cargada -- para que el menu concluyera
    que ya no habia nadie y no llegara a mandar la senal. Llamar a una puerta que no
    existe no cuesta nada; no llamarla deja un proceso de 700 MB suelto.
    """
    if not app.voila:
        peticion = urllib.request.Request(
            app.url.rstrip("/") + _servidor.RUTA_APAGADO, method="POST", data=b"")
        try:
            urllib.request.urlopen(peticion, timeout=3).read()
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            pass
        return

    pid = _pid_escrito(app)
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _pid_escrito(app: Aplicacion) -> int | None:
    """El pid que la aplicacion dejo en `.servidor.pid`, si sigue siendo suyo.

    Es el unico camino hasta un simulador que el menu no lanzo -- abierto a mano o por
    doble clic --, porque de ese no tiene ningun proceso en la mano y Voila no tiene
    ruta de apagado.

    El archivo se comprueba contra la tabla de procesos antes de usarlo. `app.py` lo
    borra al salir pase lo que pase, pero un `SIGKILL` no le da ocasion, y el sistema
    reasigna los pid: un archivo olvidado apunta tarde o temprano a un proceso ajeno.
    Mandar `SIGTERM` a ese numero por fiarse de un archivo es exactamente el fallo que
    el propio boton del simulador se cuido de no cometer.
    """
    try:
        pid = int((app.carpeta / ARCHIVO_PID).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid <= 0:
        return None
    if ES_WINDOWS:
        # Sin `ps`, y `tasklist` no da la linea de ordenes completa sin privilegios. Se
        # confia en el archivo, que en Windows el unico camino que lo escribe es el
        # mismo que lo borra.
        return pid
    try:
        salida = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="],
                                capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    return pid if app.carpeta.name in salida.stdout else None


def _senalar_al_grupo(proceso: subprocess.Popen, senal) -> None:
    """Manda la senal al proceso y a todo lo que cuelga de el.

    Al gestor solo no basta: espera a la aplicacion con `subprocess.run`, que no reenvia
    senales. Ver el encabezado del modulo.
    """
    try:
        if ES_WINDOWS:
            # No hay grupos de procesos que valgan aqui: `taskkill /T` recorre el arbol.
            # Es siempre forzoso, asi que el intento suave de arriba -- la puerta propia
            # de la aplicacion -- es el unico apagado limpio que hay en Windows.
            subprocess.run(["taskkill", "/PID", str(proceso.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proceso.pid), senal)
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
        # El grupo ya no existe, o nunca se pudo aislar. Queda el proceso suelto.
        try:
            proceso.send_signal(senal)
        except (ProcessLookupError, PermissionError, OSError, ValueError):
            pass


def _esperar_a_que_suelte(app: Aplicacion, limite: float = 12.0) -> bool:
    """Espera a que el puerto quede libre. De paso recoge el proceso muerto.

    Lo que se vigila es el PUERTO y no el proceso, porque es el puerto lo que necesita
    la siguiente apertura. Un gestor que ya salio con su nieto todavia escuchando
    parece un apagado consumado y no lo es.

    Doce segundos por defecto y no cinco: apagarse bien le cuesta a Voila lo que tarde
    en cerrar sus kernels, y se han visto seis vivos a la vez. Rendirse antes escala a
    matar el grupo, y eso deja esos kernels huerfanos -- 700 MB cada uno -- en vez de
    cerrados. Aqui la prisa sale cara y la paciencia no cuesta nada: en el unico caso
    frecuente, el tablero suelta el puerto en menos de un segundo y no se espera nada.
    """
    t0 = time.perf_counter()
    while True:
        proceso = app.proceso
        if proceso is not None and proceso.poll() is not None:
            # `poll` ademas lo recoge: sin esto queda un zombi por cada apertura.
            app.proceso = None
        if not _ocupado(app.puerto):
            return True
        if time.perf_counter() - t0 >= limite:
            return False
        time.sleep(0.2)


def _anotar_apagado(app: Aplicacion, libre: bool) -> None:
    """Deja en la tarjeta lo que de verdad paso."""
    if libre:
        app.fase, app.detalle = "detenida", ""
        return
    app.fase = "fallo"
    app.detalle = (
        f"sigue habiendo algo sirviendo en el puerto {app.puerto} y no lo lanzo este "
        f"menu, asi que no se le manda ninguna senal. Cierralo desde donde se abrio.")


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
            # Apagar aqui mismo y contestar despues, al reves que antes: la pagina
            # necesita saber si quedo algo vivo, y eso no se sabe hasta haberlo
            # intentado. Lo que no puede pasar aqui es cerrar el servidor -- eso si se
            # bloquearia contra si mismo --, asi que eso sigue yendo en otro hilo.
            #
            # `sendBeacon`, que es como llegan los tableros, no lee esta respuesta. No
            # importa: su pestania se esta cerrando de todas formas, y quien pulso desde
            # el menu -- que es quien se queda mirando -- si la lee.
            supervivientes = self.control.apagar_todo()
            self._json({"cerrado": not supervivientes, "vivas": supervivientes})
            threading.Timer(0.3, self.server.shutdown).start()
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
