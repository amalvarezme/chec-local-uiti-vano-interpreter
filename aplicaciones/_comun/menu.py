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

## Cada aplicacion abre su PROPIA ventana de terminal

"Abrir" no lanza un proceso mudo: abre una ventana de Terminal nueva, con la salida de
esa aplicacion a la vista, y esa ventana se cierra sola cuando el tablero se cierra. La
ventana la abre `_comun/terminal.py`, que es el unico sitio del proyecto que sabe hacerlo
sin que Ghostty se la quede -- ver ahi el detalle medido, que es el mismo motivo por el
que el doble clic va por `Iniciar.app` y no por un `.command`.

Consecuencia que hay que tener presente al tocar el apagado: **cuando una aplicacion vive
en su ventana, el menu NO tiene su proceso en la mano.** Lo lanzo Terminal.app, que ya
estaba corriendo. Lo que el menu ejecuto fue `open`, que vuelve en cuanto entrega el
perfil. Por eso `Aplicacion.en_ventana` existe, por eso `_esperar` no recibe ese proceso
-- verlo muerto le haria rendirse en el acto -- y por eso el respaldo del apagado va al
pid que la aplicacion deja escrito en `.servidor.pid`.

Se cae al arranque en segundo plano -- lo que habia antes -- si el sistema no sabe abrir
ventanas (Linux) o si el lanzador falla. Nunca se deja de abrir el tablero por no haber
podido abrir su ventana.

## Y por que la senal va al GRUPO, no al proceso

Lo que el menu tiene en la mano no es la aplicacion: es el gestor. La cadena real son
tres o cuatro procesos.

    menu.py  --open-->  Terminal.app  -->  gestor.py  -->  app.py  --Popen-->  voila
    menu.py  --Popen-->  gestor.py  --subprocess.run-->  app.py  --Popen-->  voila

`subprocess.run` no reenvia senales. Un `SIGTERM` al gestor lo mata a el y deja al de
abajo -- el que tiene el puerto -- vivo y sin padre, con el menu informando de que lo
cerro. Por eso cada hijo se lanza en su propia sesion (`start_new_session`) o grupo de
procesos en Windows: eso convierte "alcanzar a los nietos" en una sola llamada, sin
recorrer la tabla de procesos ni depender de `ps`. En la primera cadena el grupo es el
trabajo en primer plano de la ventana, y se alcanza igual desde el pid escrito.

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

La regla vale en las dos direcciones, y la otra mitad se agrego despues: una aplicacion
abierta POR FUERA -- doble clic sobre su `Iniciar.app`, o un `/app-local-*` -- tampoco
puede salir como "detenida". El menu solo se enteraba de lo que habia lanzado el, asi que
su tarjeta ofrecia "Abrir" sobre un tablero que ya estaba sirviendo, y "Cerrar todo" lo
apagaba igual -- porque llama a la puerta de cada puerto --: la pantalla contaba una cosa
y la maquina hacia otra. La fase sale del PUERTO, no de la memoria del menu.
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
import terminal as _terminal  # noqa: E402
from menu_pagina import pagina  # noqa: E402

RAIZ_APPS = Path(__file__).resolve().parents[1]
GESTOR = Path(__file__).resolve().parent / "gestor.py"

ES_WINDOWS = os.name == "nt"

# Donde cada aplicacion deja escrito el pid del proceso que tiene su puerto. Sale de
# `servidor.py`, que es el que lo escribe: tenerlo declarado dos veces era una manera de
# que los dos extremos se separaran sin que nada avisara, y el sintoma habria sido un
# simulador que el menu no puede apagar.
ARCHIVO_PID = _servidor.ARCHIVO_PID

# Cada hijo, en su propia sesion (POSIX) o grupo (Windows). Es lo que despues permite
# alcanzar de una sola llamada al nieto que tiene el puerto. Ver el encabezado.
_AISLAR_GRUPO = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if ES_WINDOWS
                 else {"start_new_session": True})

# La escalada del apagado, y no es la misma en los dos sistemas.
#
# En POSIX son dos pasos: `SIGTERM` para que el hijo cierre por su cuenta y `SIGKILL`
# para el que no ceda. En Windows **`SIGKILL` no existe** -- nombrarlo revienta con
# `AttributeError` en mitad del apagado, con las aplicaciones ya a medio cerrar, que es
# el peor sitio posible para descubrirlo. Y ademas sobra: alli la senal no viaja por
# grupos, la reparte `taskkill /T /F`, que ya es forzoso y recorre el arbol entero. Un
# solo paso hace lo que en POSIX hacen los dos.
_ESCALADA = (((signal.SIGTERM, 5.0),) if ES_WINDOWS
             else ((signal.SIGTERM, 3.0), (signal.SIGKILL, 2.0)))

# Puerto del menu. Fijo, como los de las aplicaciones: es la URL que el usuario deja
# en un marcador y la que los tableros necesitan para saber a donde volver.
PUERTO_MENU = 8800


class Aplicacion:
    """Una de las cinco aplicaciones gobernadas, y el proceso que la sirve."""

    __slots__ = ("clave", "carpeta", "titulo", "descripcion", "puerto", "voila",
                 "proceso", "en_ventana", "fase", "detalle")

    def __init__(self, clave, carpeta, titulo, descripcion, puerto, *, voila=False):
        self.clave = clave
        self.carpeta = RAIZ_APPS / carpeta
        self.titulo = titulo
        self.descripcion = descripcion
        self.puerto = puerto
        self.voila = voila
        self.proceso: subprocess.Popen | None = None
        # Si esta aplicacion vive en una ventana de terminal propia. Cuando es asi el
        # menu NO tiene su proceso en la mano -- lo lanzo Terminal.app, que ya estaba
        # corriendo --, y el apagado tiene que ir por el pid que la aplicacion deja
        # escrito. Ver `_apagar_aplicacion`.
        self.en_ventana = False
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
            propias = {"PYTHONUNBUFFERED": "1",
                       "MENU_CRITICIDAD": f"http://127.0.0.1:{PUERTO_MENU}/"}
            _lanzar(app, comando, propias)
            # Construir corre DENTRO de ese proceso, asi que el plazo tiene que cubrir
            # el peor caso medido -- 71 s de cuaderno mas el arranque -- con holgura.
            #
            # El proceso solo se pasa cuando el menu lo tiene en la mano. Con la
            # aplicacion en su propia ventana, lo que el menu lanzo fue `open`, que
            # vuelve en cuanto Terminal recibe el perfil: pasarlo haria que `_esperar`
            # se rindiera en el acto -- ve un proceso muerto -- y toda apertura saldria
            # como "el servidor no respondio" con el tablero levantandose detras.
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
        # Y AL FINAL, las ventanas que no se cerraron solas. Una ventana se cierra sola
        # cuando su comando termina bien; la de una aplicacion que no llego a arrancar
        # -- porque otra cosa tenia su puerto -- se para en un `read` a que lean el
        # error y se queda ahi para siempre. No tiene puerto, asi que nada de lo de
        # arriba la ve, y se acumula una por intento.
        #
        # Va despues y no antes: cerrar la ventana de una aplicacion que todavia esta
        # soltando su puerto -- y en el simulador, sus kernels -- es como se queda un
        # proceso de 700 MB huerfano.
        _terminal.cerrar_ventanas()
        self.apagando.set()
        return supervivientes

    # -------------------------------------------------------------------- estado

    def estado_de(self, app: Aplicacion) -> dict:
        if app.fase == "corriendo" and not app.viva() and not _ocupado(app.puerto):
            # Se cerro por su cuenta: con su propio boton, o con Ctrl+C en su ventana.
            app.fase, app.detalle = "detenida", ""
        elif app.fase == "detenida" and _ocupado(app.puerto):
            # Y al reves: alguien la abrio por fuera -- doble clic sobre su `Iniciar.app`,
            # o un `/app-local-*` --. Antes la tarjeta seguia diciendo "detenida" con el
            # boton "Abrir" encima mientras el tablero servia, y "Cerrar todo" lo apagaba
            # igual, porque llama a la puerta de cada puerto: la pantalla contaba una cosa
            # y la maquina hacia otra.
            #
            # Se pregunta solo por el PUERTO y no por el pid: esto corre para las cinco
            # aplicaciones en cada `/estado`, o sea cada 2,5 s, y `pid_de` arranca un `ps`.
            # Una conexion TCP no cuesta nada; dos subprocesos por segundo, si.
            app.fase = "corriendo"
            app.detalle = f"abierta fuera de este menu, en el puerto {app.puerto}"
        return {
            "clave": app.clave, "titulo": app.titulo, "descripcion": app.descripcion,
            "puerto": app.puerto, "url": app.url, "fase": app.fase,
            "detalle": app.detalle, "instalada": app.instalada(),
            "construida": app.construida(),
        }

    def estado(self) -> list[dict]:
        return [self.estado_de(app) for app in self.apps.values()]


# ----------------------------------------------------------------------- ayudas


# La pregunta "esta el puerto tomado" -- una conexion TCP, nunca un `GET /`, que con
# Voila cuesta un kernel de ~700 MB por sondeo. Vive en `servidor.py` porque la hacen los
# dos: el menu para vigilar, y cada aplicacion al arrancar para no duplicarse.
_ocupado = _servidor.puerto_tomado

# Las claves que trae cada tarjeta de `/estado`. Se usan para reconocer a otro menu en el
# puerto, y se sacan de una sola tarjeta de verdad para que anadir o quitar un campo no
# deje esta comprobacion mirando algo que ya no existe.
_CAMPOS_DE_ESTADO = frozenset(("clave", "titulo", "puerto", "fase", "instalada"))


def es_un_menu(puerto: int) -> bool:
    """Si lo que hay en `puerto` es un CriticidadCHEC, sea de la copia que sea.

    Existe porque la otra manera de contestarlo -- comparar la carpeta de la aplicacion
    contra la linea de ordenes del proceso, que es lo que hace `servidor.pid_de` -- dice
    que no cuando el menu vivo salio de OTRO clon del repositorio, o de un worktree. Y
    entonces el doble clic concluia "el puerto lo tiene algo, y no es CriticidadCHEC":
    salia con error, dejaba la ventana abierta sobre el mensaje, y no abria nada. Una
    ventana atascada mas por cada intento.

    La pregunta correcta no es de quien es el proceso, sino que contesta el puerto.

    Se pide `/estado` y NUNCA `/`: este sondeo cae sobre un puerto que puede tener
    cualquier cosa detras, y pedirle `/` a la cosa equivocada -- Voila -- cuesta un
    kernel de ~700 MB. `/estado` solo lo sirve el menu, y lo que devuelve es barato.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/estado",
                                    timeout=2) as respuesta:
            dato = json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            json.JSONDecodeError, UnicodeDecodeError):
        return False
    # Una lista de tarjetas con la forma de las nuestras. Que conteste 200 no basta:
    # cualquier servidor puede tener un `/estado`, y adoptar el suyo como si fuera el
    # menu es abrirle al usuario la pagina de otro en la URL que tiene en el marcador.
    return (isinstance(dato, list) and bool(dato)
            and all(isinstance(t, dict) and _CAMPOS_DE_ESTADO <= t.keys()
                    for t in dato))


def _lanzar(app: Aplicacion, comando: list[str], propias: dict[str, str]) -> None:
    """Levanta la aplicacion en su PROPIA ventana de terminal, o en segundo plano.

    La ventana no es cosmetica y es lo que el usuario pidio: cada tablero tiene la suya,
    con su salida a la vista, y se cierra sola cuando el tablero se cierra -- eso lo hace
    el `shellExitAction` del perfil, no el menu. Antes las cinco aplicaciones corrian con
    `stdout=DEVNULL` colgando del menu: no habia ninguna ventana que cerrar, y lo que
    fuera mal solo dejaba rastro en el detalle de la tarjeta.

    Se cae al arranque en segundo plano -- que es exactamente lo que habia -- cuando el
    sistema no sabe abrir ventanas (Linux) o cuando el lanzador falla. Caerse es
    deliberado: quedarse sin abrir el tablero porque no hubo ventana seria cambiar un
    inconveniente por una aplicacion que no arranca.
    """
    if _terminal.abrir_ventana(comando, etiqueta=app.clave, entorno=propias,
                               directorio=app.carpeta):
        # La ventana es de Terminal.app, que ya estaba corriendo: el menu no tiene ningun
        # proceso que vigilar ni al que senalar. El apagado va por el pid escrito.
        app.proceso, app.en_ventana = None, True
        return
    app.en_ventana = False
    app.proceso = subprocess.Popen(comando, env=dict(os.environ, **propias),
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   **_AISLAR_GRUPO)


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

    Y la ventana de terminal no se cierra desde aqui, a proposito: se cierra sola en
    cuanto su comando termina, que es lo que pide el `shellExitAction` del perfil. Es la
    misma cadena de siempre -- el paso 1 hace salir a la aplicacion, con ella salen el
    gestor y el trampolin, y Terminal cierra la ventana --, asi que cerrar puertos y
    cerrar ventanas son el mismo acto y no dos. Ir a por la ventana aparte exigiria
    AppleScript, que es justo lo que no se puede usar aqui: sin el permiso de
    Automatizacion la llamada no falla, se queda colgada.
    """
    if app.proceso is None and not app.en_ventana and not _ocupado(app.puerto):
        return True

    _pedir_por_su_puerta(app)
    if _esperar_a_que_suelte(app):
        return True

    # El respaldo, por el camino que haya. Con la aplicacion en su propia ventana el
    # menu no tiene proceso que senalar -- lo lanzo Terminal.app --, asi que se va al pid
    # que la aplicacion misma dejo escrito y se senala a SU grupo, que es el trabajo en
    # primer plano de esa ventana: el gestor, la aplicacion, Voila y sus kernels. Nunca
    # alcanza a Terminal.app, que vive en otro grupo.
    for senal, plazo in _ESCALADA:
        if app.proceso is not None:
            _senalar_al_grupo(app.proceso, senal)
        elif not _senalar_al_pid_escrito(app, senal):
            break
        if _esperar_a_que_suelte(app, plazo):
            return True
    return not _ocupado(app.puerto)


def _senalar_al_pid_escrito(app: Aplicacion, senal) -> bool:
    """Senala al grupo del pid que la aplicacion dejo en `.servidor.pid`.

    Devuelve si habia a quien senalar. `pid_de` ya comprueba el archivo contra la tabla
    de procesos, asi que un pid olvidado por un `SIGKILL` -- que el sistema acaba
    reasignando a otro proceso -- no llega hasta aqui. Sin esa comprobacion esto seria
    mandarle una senal a algo que no es la aplicacion por fiarse de un archivo.
    """
    pid = _servidor.pid_de(app.carpeta)
    if pid is None:
        return False
    try:
        if ES_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(pid), senal)
        return True
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
        return False


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
        if ES_WINDOWS:
            # `os.kill(pid, SIGTERM)` NO es aqui lo que parece: CPython lo implementa
            # como `TerminateProcess`, que mata a Voila en seco, sin darle ocasion de
            # cerrar sus kernels. Cada uno es un `python.exe` de ~780 MB que queda
            # huerfano, y el puerto SI queda libre -- asi que el menu informaba de un
            # apagado limpio con hasta siete procesos vivos detras, que es justo lo que
            # `PROBAR-EN-WINDOWS.md` comprueba en su paso 9.
            #
            # `taskkill /T` recorre el arbol, que es donde viven esos kernels. Es
            # forzoso igual -- en Windows no hay un apagado suave que Voila atienda --,
            # pero al menos no deja nada detras.
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=10)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
        pass


def _pid_escrito(app: Aplicacion) -> int | None:
    """El pid que la aplicacion dejo en `.servidor.pid`, si sigue siendo suyo.

    Es el unico camino hasta un simulador que el menu no lanzo -- abierto a mano o por
    doble clic --, porque de ese no tiene ningun proceso en la mano y Voila no tiene
    ruta de apagado.

    La comprobacion contra la tabla de procesos la hace `servidor.pid_de`, que es donde
    vive tambien la escritura del archivo. Un pid olvidado por un `SIGKILL` apunta tarde
    o temprano a un proceso ajeno, y mandarle `SIGTERM` por fiarse de un archivo es
    exactamente el fallo que el propio boton del simulador se cuido de no cometer.
    """
    return _servidor.pid_de(app.carpeta)


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
        # Con el puerto libre su ventana ya se cerro sola: el comando termino, y eso es
        # lo que la cierra. Dejar la marca puesta haria que el siguiente apagado buscara
        # un pid de una ventana que ya no existe.
        app.en_ventana = False
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
        # Sin `Access-Control-Allow-Origin`. Lo llevaba para que el "Cerrar todo" de los
        # tableros -- que viven en otro puerto, o sea otro origen -- pudiera llegar hasta
        # aqui. Ese boton ya no existe: desde un tablero solo se apaga ese tablero, y
        # todo lo que pide esta pagina sale de su mismo origen.
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, formato: str, *args) -> None:
        if not self.silencioso:
            super().log_message(formato, *args)


class _Servidor(socketserver.ThreadingTCPServer):
    # La MISMA regla que `servidor.py`, y por el mismo motivo. En Windows
    # `SO_REUSEADDR` no significa lo que en POSIX: permite atarse a un puerto que otro
    # proceso ESTA escuchando ahora mismo, sin error, y el sistema reparte las
    # conexiones entre los dos. Aqui eso seria un segundo menu robandole peticiones al
    # primero -- y encima con el guardian de `revisar_puerto` apoyado en `pid_de`, que
    # alli es el que menos garantias da.
    #
    # Estaba en `True` fijo, y el test que vigila esta regla solo miraba `servidor.py`.
    allow_reuse_address = not ES_WINDOWS
    daemon_threads = True


def _parametro(ruta: str, nombre: str) -> str:
    consulta = ruta.split("?", 1)[1] if "?" in ruta else ""
    return urllib.parse.parse_qs(consulta).get(nombre, [""])[0]


def servir_menu(*, abrir: bool = True, puerto: int | None = None,
                verboso: bool = False, app: Path | None = None) -> int:
    """Levanta el menu y no vuelve hasta que se cierre todo.

    `app` es la carpeta de CriticidadCHEC. Con ella, un segundo doble clic sobre el menu
    ya abierto abre el que esta corriendo en vez de morir con un `OSError` -- el puerto
    8800 no se puede reusar -- dejando la ventana nueva sobre una traza de Python.
    """
    control = Control()
    manejador = type("Manejador", (_Manejador,), {
        "control": control, "silencioso": not verboso})
    puerto = puerto or PUERTO_MENU

    if app is not None:
        codigo = _servidor.revisar_puerto(app, puerto, abrir=abrir,
                                          titulo="CriticidadCHEC",
                                          identificar=es_un_menu)
        if codigo is not None:
            return codigo

    with _Servidor(("127.0.0.1", puerto), manejador) as servidor_menu:
        if app is not None:
            _servidor.escribir_pid(app)
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
        finally:
            # Un pid olvidado apunta tarde o temprano a otro proceso, y la siguiente
            # apertura lo leeria como "el menu ya esta abierto" sobre un puerto ajeno.
            if app is not None:
                _servidor.borrar_pid(app)
    return 0
