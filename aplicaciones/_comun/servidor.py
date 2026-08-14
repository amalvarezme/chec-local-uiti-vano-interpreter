"""Servidor local para los tableros ya empaquetados.

No es `python -m http.server` por tres razones concretas, todas medibles:

1. **Entrega los `.gz` que dejo el empaquetador.** `http.server` no negocia
   compresion, asi que los 27,8 MB del tablero de clima viajarian enteros. Con los
   `.gz` precomprimidos viajan 6,5 MB y el servidor no gasta CPU: los bytes ya
   estaban comprimidos en disco desde la construccion.
2. **Pone las cabeceras de cache.** `http.server` manda `no-cache` implicito, asi
   que plotly.js y los datos se vuelven a bajar en cada apertura. Aqui las piezas
   con hash en el nombre salen `immutable`, y la segunda apertura del tablero
   transfiere solo el armazon.
3. **Elige un puerto libre.** El 8000 esta ocupado en cualquier maquina de trabajo,
   y el fallo de `http.server` en ese caso es una traza de `OSError` que no dice
   que hacer.

Sirve UNA carpeta y nada mas: cualquier ruta que se salga de ella devuelve 404 sin
tocar el disco.
"""
from __future__ import annotations

import gzip
import http.server
import mimetypes
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import paleta as _paleta

# Ruta del boton de cerrar. Vive aqui y no en el empaquetador porque los dos extremos
# -- el boton que la llama y el servidor que la atiende -- tienen que coincidir.
RUTA_APAGADO = "/apagar"

# Donde cada aplicacion deja escrito el pid del proceso que tiene su puerto.
#
# Sirve para dos cosas distintas y las dos importan. Al ABRIR, es como se reconoce que
# el puerto lo tiene esa misma aplicacion y no un programa ajeno, sin pedirle ninguna
# pagina -- preguntarle una a Voila cuesta un kernel de ~700 MB, medido. Al CERRAR, es
# el unico camino que tiene CriticidadCHEC hasta un simulador que no lanzo el.
ARCHIVO_PID = ".servidor.pid"

# Un ano. Solo se aplica a archivos cuyo nombre contiene el hash de su contenido:
# si cambian, cambia la URL, asi que no hay forma de servir algo viejo.
_CACHE_INMUTABLE = "public, max-age=31536000, immutable"
# El armazon no lleva hash -- es la URL de entrada --, asi que se revalida siempre.
# Con ETag, revalidar cuesta un 304 de cero bytes cuando no cambio.
_CACHE_REVALIDAR = "no-cache"


class _Pieza:
    __slots__ = ("ruta", "tipo", "cache", "etag", "gz", "tam", "crudo")

    def __init__(self, ruta: Path, inmutable: bool, datos: bytes | None = None):
        self.ruta = ruta
        tipo, _ = mimetypes.guess_type(ruta.name)
        self.tipo = tipo or "application/octet-stream"
        self.cache = _CACHE_INMUTABLE if inmutable else _CACHE_REVALIDAR
        # `datos` solo llega cuando la pieza no es el archivo de disco tal cual -- hoy,
        # el armazon con la barra del menu inyectada. En ese caso hay que guardar el
        # crudo en memoria: releerlo del disco devolveria la version sin barra.
        self.crudo = datos
        if datos is None:
            datos = ruta.read_bytes()
        self.tam = len(datos)
        self.etag = f'"{hash((ruta.name, self.tam)) & 0xFFFFFFFF:08x}"'
        # Solo el comprimido queda en memoria (6,5 MB para el tablero mas pesado).
        # El crudo se lee de disco si algun cliente no acepta gzip, que en la practica
        # no pasa: todos los navegadores desde 2010 lo anuncian.
        gz = ruta.parent / f"{ruta.name}.gz"
        if self.crudo is None and gz.exists():
            self.gz = gz.read_bytes()
        else:
            # Con la barra inyectada el `.gz` de disco ya no corresponde: se recomprime.
            # Son 69 KB de armazon, no los 4,6 MB de plotly.
            self.gz = gzip.compress(datos, 6, mtime=0)


# Convencion del empaquetador: el hash del contenido va justo antes de la extension.
# Se busca ESA posicion y no se cuentan puntos: `plotly-3.7.0.8ef4c6ab13.js` trae dos
# puntos en el numero de version, asi que contar segmentos lo dejaba fuera del cache
# eterno -- y es justamente la pieza que las dos aplicaciones comparten.
_NOMBRE_CON_HASH = re.compile(r"\.[0-9a-f]{10}\.[^.]+$")


def _catalogo(carpeta: Path) -> dict[str, _Pieza]:
    piezas: dict[str, _Pieza] = {}
    for archivo in sorted(carpeta.iterdir()):
        if not archivo.is_file() or archivo.suffix == ".gz":
            continue
        inmutable = _NOMBRE_CON_HASH.search(archivo.name) is not None
        piezas["/" + archivo.name] = _Pieza(archivo, inmutable)
    if "/index.html" not in piezas:
        raise SystemExit(f"{carpeta} no contiene index.html; falta construir el tablero.")
    piezas["/"] = piezas["/index.html"]
    return piezas


# Barra que se inyecta SOLO cuando el tablero fue lanzado desde CriticidadCHEC. No
# viene empaquetada en el `index.html` porque depende de la URL del menu, que no se
# conoce hasta que alguien arranca el menu y le toca un puerto.
#
# `window.close()` aqui es fiable, y por un motivo distinto al del boton suelto: el
# menu abre estas pestanias con `window.open()`, y una ventana que abrio un script SI
# la puede cerrar un script, sin la condicion del historial propio. El respaldo se
# queda igualmente, porque una pestania duplicada a mano por el usuario ya no cumple
# esa condicion y se veria exactamente igual.
_BARRA_MENU = """
<div id="barra-menu" style="position:fixed;top:10px;right:12px;z-index:10000;
     display:flex;gap:8px;font:13px/1 __FUENTE__;font-weight:600;">
  <button type="button" id="bm-volver" title="Apaga este tablero y vuelve al menu"
    style="font:inherit;padding:6px 12px;border:1px solid __BORDE_FUERTE__;
           border-radius:4px;background:__FONDO__;color:__TEXTO__;cursor:pointer;
           box-shadow:0 1px 3px rgba(0,0,0,.12);"
    >&larr; Volver al menu</button>
  <button type="button" id="bm-cerrar" title="Apaga este tablero y cierra esta pestana"
    style="font:inherit;padding:6px 12px;border:1px solid __ACENTO__;
           border-radius:4px;background:__FONDO__;color:__ACENTO__;cursor:pointer;
           box-shadow:0 1px 3px rgba(0,0,0,.12);"
    >Cerrar</button>
</div>
<script>
(function () {
  // El boton suelto de cerrar sobra cuando hay menu: apaga lo mismo que el "Cerrar" de
  // la barra, pero dejando la pestania abierta sobre un tablero muerto.
  var suelto = document.getElementById('cerrar-tablero');
  if (suelto) { suelto.remove(); }

  var MENU = '__MENU__';

  function despedirse(texto) {
    document.body.innerHTML =
      '<div style="font:16px/1.6 __FUENTE_JS__;padding:40px;max-width:640px;' +
      'margin:0 auto;color:__TEXTO__;border-left:__FILO__;background:__PANEL__;' +
      'border-radius:6px;">' +
      '<h1 style="font-size:20px;margin:0 0 12px;">' + texto + '</h1>' +
      '<p>Ya puedes cerrar esta pestana.</p></div>';
  }

  function apagarme() {
    // El servidor puede morir antes de contestar; eso es exito, no fallo.
    return fetch('__RUTA__', { method: 'POST' }).catch(function () {});
  }

  document.getElementById('bm-volver').addEventListener('click', function () {
    document.getElementById('barra-menu').remove();
    apagarme().then(function () {
      window.close();
      setTimeout(function () {
        if (window.closed) { return; }
        // No se pudo cerrar la pestania: se vuelve al menu por navegacion, que deja al
        // usuario donde pidio ir en vez de en una pagina de despedida.
        window.location = MENU;
      }, 400);
    });
  });

  // "Cerrar" apaga ESTE tablero y nada mas: el mismo `POST /apagar` de "Volver", que se
  // lleva su servidor, su puerto y lo que cuelgue de el. Las otras aplicaciones no son
  // asunto suyo -- el unico apagado general es el "Cerrar todo" de la pagina del menu --
  // y el menu se entera solo, porque revisa los cinco puertos cada 2,5 s.
  //
  // Los dos botones de la barra hacen lo mismo con los procesos y se diferencian en
  // donde dejan al usuario: "Volver" lo devuelve al menu, "Cerrar" lo deja fuera.
  document.getElementById('bm-cerrar').addEventListener('click', function () {
    document.getElementById('barra-menu').remove();
    apagarme().then(function () {
      window.close();
      setTimeout(function () {
        if (window.closed) { return; }
        despedirse('Tablero cerrado');
      }, 400);
    });
  });
})();
</script>
"""


def _con_barra_de_menu(html: bytes, menu: str) -> bytes:
    """Inserta la barra del menu antes de `</body>`.

    Falla ruidosamente si no encuentra donde ponerla. Un tablero servido sin barra se
    veria bien y dejaria al usuario sin manera de volver ni de cerrar desde el
    navegador, que es justo lo que el menu promete.
    """
    texto = html.decode("utf-8")
    if "</body>" not in texto:
        raise SystemExit(
            "El tablero no tiene </body>; no se pudo insertar la barra del menu.")
    barra = _BARRA_MENU.replace("__MENU__", menu).replace("__RUTA__", RUTA_APAGADO)
    barra = _paleta.aplicar(barra)
    return texto.replace("</body>", barra + "</body>", 1).encode("utf-8")


class _Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    piezas: dict[str, _Pieza] = {}
    silencioso = True

    def do_GET(self) -> None:  # noqa: N802 -- nombre impuesto por BaseHTTPRequestHandler
        self._responder(cuerpo=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._responder(cuerpo=False)

    def do_POST(self) -> None:  # noqa: N802
        """Unica ruta que escribe algo: el boton de cerrar del tablero.

        Es POST y no GET a proposito. Un GET que apaga el servidor lo dispara
        cualquier cosa que recorra enlaces -- el prefetch del propio navegador, sin ir
        mas lejos --, y el tablero se cerraria solo sin que nadie tocara nada.
        """
        if self.path.split("?", 1)[0] != RUTA_APAGADO:
            self.send_error(404, "No encontrado")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "8")
        self.end_headers()
        self.wfile.write(b"cerrando")
        # `shutdown()` desde el hilo que atiende la peticion se bloquea a si mismo:
        # espera a que el bucle de servicio termine, y ese bucle esta esperando a que
        # esta peticion termine. Va en un hilo aparte, y con un respiro para que la
        # respuesta llegue completa antes de que el socket se cierre.
        threading.Timer(0.2, self.server.shutdown).start()

    def _responder(self, *, cuerpo: bool) -> None:
        ruta = self.path.split("?", 1)[0].split("#", 1)[0]
        pieza = self.piezas.get(ruta)
        if pieza is None:
            self.send_error(404, "No encontrado")
            return

        if self.headers.get("If-None-Match") == pieza.etag:
            self.send_response(304)
            self.send_header("ETag", pieza.etag)
            self.send_header("Cache-Control", pieza.cache)
            self.end_headers()
            return

        acepta_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if acepta_gzip:
            datos = pieza.gz
        else:
            datos = pieza.crudo if pieza.crudo is not None else pieza.ruta.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", pieza.tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", pieza.cache)
        self.send_header("ETag", pieza.etag)
        if acepta_gzip:
            self.send_header("Content-Encoding", "gzip")
            # Sin esto, un proxy intermedio puede servir la version comprimida a un
            # cliente que no la pidio.
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        if cuerpo:
            self.wfile.write(datos)

    def log_message(self, formato: str, *args) -> None:
        if not self.silencioso:
            super().log_message(formato, *args)


# `SO_REUSEADDR` significa cosas OPUESTAS en los dos sistemas, asi que se pregunta.
#
# En POSIX permite volver a tomar un puerto que quedo en TIME_WAIT: sin ella, cerrar y
# reabrir el tablero en menos de dos minutos falla con "Address already in use".
#
# En Windows permite que un SEGUNDO proceso se ate a un puerto que YA esta escuchando y
# se lo robe -- sin error y sin aviso, con dos servidores repartiendose las peticiones
# del mismo puerto. Alli vale mas el fallo ruidoso.
_REUSAR_DIRECCION = os.name != "nt"


class _Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = _REUSAR_DIRECCION
    daemon_threads = True


def abrir_navegador(url: str) -> bool:
    """Abre `url` en el navegador por defecto. Devuelve si lo consiguio.

    En macOS se usa `/usr/bin/open` y NO el modulo `webbrowser`. `webbrowser` alli
    resuelve a `MacOSXOSAScript`, que le habla al navegador por Apple Events: eso
    exige el permiso de Automatizacion, macOS se lo pide a Terminal la primera vez, y
    si nadie lo concede -- o el dialogo sale detras de otra ventana -- la llamada
    falla sin decir nada y el tablero se queda servido pero sin abrir. `open` es el
    lanzador del sistema y no pide ese permiso.
    """
    try:
        if sys.platform == "darwin":
            return subprocess.run(["/usr/bin/open", url], capture_output=True).returncode == 0
        if os.name == "nt":
            os.startfile(url)  # noqa: S606 -- el lanzador de Windows, sin shell
            return True
        import webbrowser

        return webbrowser.open(url)
    except Exception:
        # Que no se pueda abrir el navegador no es motivo para tumbar el servidor: la
        # URL esta impresa y se puede pegar a mano.
        return False


# --------------------------------------------------------- ya esta abierta?


def puerto_tomado(puerto: int, espera: float = 0.6) -> bool:
    """Si hay alguien ESCUCHANDO en ese puerto. Se abre una conexion y se cierra.

    La pregunta no es "que sirve ahi" sino "esta el puerto tomado", y se contesta con
    una conexion TCP a proposito. Un `GET /` haria que Voila RENDERIZARA el cuaderno:
    medido, cada comprobacion de salud dejaba atras un kernel de ~700 MB con PyTorch
    dentro, y preguntar tres veces llevaba la aplicacion de uno a seis kernels.

    Es ademas la misma pregunta que contesta el `lsof ... -sTCP:LISTEN` del contrato de
    `/app-local-*`, asi que la aplicacion y quien la vigila ven lo mismo.
    """
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=espera):
            return True
    except OSError:
        return False


def escribir_pid(app: Path) -> Path:
    """Deja el pid de ESTE proceso en la carpeta de la aplicacion."""
    archivo = app / ARCHIVO_PID
    archivo.write_text(str(os.getpid()), encoding="utf-8")
    return archivo


def borrar_pid(app: Path) -> None:
    (app / ARCHIVO_PID).unlink(missing_ok=True)


def pid_de(app: Path) -> int | None:
    """El pid que la aplicacion dejo escrito, si sigue siendo suyo.

    El archivo se comprueba contra la tabla de procesos antes de devolverlo. Quien lo
    escribe lo borra al salir, pero un `SIGKILL` no le da ocasion, y el sistema reasigna
    los pid: un archivo olvidado apunta tarde o temprano a un proceso ajeno. Dar ese
    numero por bueno es como se le manda una senal a algo que no es la aplicacion, o
    como una apertura nueva concluye que el puerto es suyo cuando lo tiene otro.

    Se compara contra la RUTA de la aplicacion y no contra el nombre de su carpeta: la
    ruta aparece entera en la linea de ordenes de los tres procesos que pueden tener el
    puerto -- `app.py`, el servidor de los tableros y el Voila del simulador, que abre
    el cuaderno de dentro de esa misma carpeta -- y no la comparte ningun otro proceso
    de la maquina.
    """
    try:
        pid = int((app / ARCHIVO_PID).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        # `tasklist` no da la linea de ordenes, asi que alli no se puede comparar contra
        # la RUTA de la aplicacion como abajo. Pero si da el NOMBRE DE IMAGEN, y eso ya
        # descarta lo que de verdad pasa: que el archivo se quede rancio -- un `taskkill
        # /F` no deja correr el `borrar_pid` del `finally` -- y que Windows, que recicla
        # los pid en un espacio pequenio, se lo haya dado a otra cosa.
        #
        # Confiar en el archivo a secas era lo que dejaba dos agujeros: `menu.py` manda
        # `taskkill /PID <pid> /T /F` sobre lo que esto devuelva, o sea que un pid
        # reciclado se llevaba por delante a un proceso ajeno y a todo su arbol; y
        # `revisar_puerto` concluia "ya se esta sirviendo" y abria el navegador sobre un
        # servidor de otro. Ninguno de los dos avisaba.
        #
        # No es tan estricto como el `ps` de abajo -- otro Python cualquiera pasaria --,
        # y aun asi es la diferencia entre matar un proceso al azar y matar como mucho
        # otro interprete. La comprobacion fuerte necesitaria `wmic`, que Windows esta
        # retirando, o PowerShell, que cuesta medio segundo por llamada.
        try:
            salida = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            # Sin poder preguntar, se conserva lo que habia: negarlo aqui dejaria al
            # simulador sin ninguna via de apagado.
            return pid
        return pid if "python" in salida.stdout.lower() else None
    try:
        salida = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="],
                                capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    return pid if str(app.resolve()) in salida.stdout else None


# Codigo de salida cuando el puerto lo tiene algo que no es esta aplicacion. Distinto de
# cero a proposito: es lo que hace que la ventana de `Iniciar.app` NO se cierre sola y
# el mensaje se quede en pantalla para que lo lean.
SALIDA_PUERTO_AJENO = 2


def revisar_puerto(app: Path, puerto: int, *, abrir: bool,
                   titulo: str | None = None) -> int | None:
    """Que hacer cuando alguien pide levantar `app` en `puerto`.

    Devuelve `None` si el puerto esta libre y hay que seguir. Si no, devuelve el codigo
    con el que hay que SALIR sin levantar nada:

      * `0` -- el puerto lo tiene esta misma aplicacion. El doble clic es "abreme esto",
        no "levanta otra copia": se abre el navegador sobre la que ya esta y se sale
        bien, que ademas es lo que cierra sola la ventana recien abierta.
      * `SALIDA_PUERTO_AJENO` -- lo tiene otra cosa. Ahi si hay algo que decidir.

    Lo que ya no puede pasar es lo de antes: `puerto_libre` caia a un puerto que
    asignara el sistema, y el segundo doble clic servia el MISMO tablero en una URL que
    nadie conocia -- medido, 01_clima en 8801 y una segunda copia en 53745 --, invisible
    para CriticidadCHEC, que busca las aplicaciones donde dice el contrato.
    """
    if not puerto_tomado(puerto):
        return None

    titulo = titulo or app.name
    url = f"http://127.0.0.1:{puerto}/"
    if pid_de(app) is not None:
        # "ya se esta sirviendo" y no "ya esta abierta": el titulo lo pone quien
        # llama y tanto puede ser un nombre de carpeta como una frase, asi que la
        # concordancia de genero no se puede dar por buena.
        print(f"\n  {titulo} ya se esta sirviendo en  {url}")
        print("  No se levanta una segunda copia: se abre la que ya esta corriendo.\n")
        if abrir and not abrir_navegador(url):
            print(f"  No se pudo abrir el navegador solo: copia {url} y pegalo.")
        return 0

    quien = (f"netstat -ano | findstr :{puerto}" if os.name == "nt"
             else f"lsof -ti tcp:{puerto} -sTCP:LISTEN")
    print(f"\n  El puerto {puerto} ya lo tiene algo, y no es {titulo}.")
    print(f"  Para ver quien:  {quien}")
    print("  Cierra eso y vuelve a abrir la aplicacion. No se levanta en otro puerto "
          "porque\n  su URL es fija: es la que espera CriticidadCHEC y la que queda en "
          "el marcador.\n")
    return SALIDA_PUERTO_AJENO


def puerto_libre(preferido: int = 8765) -> int:
    """Devuelve `preferido` si esta libre; si no, uno que el sistema asigne.

    El sondeo lleva `SO_REUSEADDR` porque el servidor que va detras lo lleva
    (`_Servidor.allow_reuse_address`), y un sondeo mas estricto que el servidor miente:
    decia "ocupado" de un puerto que el servidor si habria tomado.

    Justo despues de cerrar un tablero, su puerto queda en TIME_WAIT. Sin esta opcion el
    `bind` de prueba fallaba ahi, y volver a abrir el tablero se iba a un puerto
    aleatorio SIN DECIRLO -- misma aplicacion, otra URL, y el marcador del usuario
    apuntando a nada. Medido: `puerto_libre(57212)` devolvia 57214.
    """
    for candidato in (preferido, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # La misma pregunta que arriba, dada la vuelta: en Windows la opcion haria
            # que este sondeo diera por LIBRE un puerto que otra aplicacion esta
            # sirviendo ahora mismo.
            if _REUSAR_DIRECCION:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", candidato))
            except OSError:
                continue
            return s.getsockname()[1]
    raise SystemExit("No se pudo reservar ningun puerto local.")


def servir(carpeta: Path, *, app: Path | None = None, abrir: bool = True,
           puerto: int | None = None, preferido: int = 8765, verboso: bool = False,
           menu: str | None = None) -> int:
    """Sirve `carpeta` en 127.0.0.1 hasta que se interrumpa con Ctrl+C.

    `puerto` lo fija quien llama -- los comandos `/app-local-*` y CriticidadCHEC lo
    pasan siempre. `preferido` es para el doble clic, que no pasa ninguno: cada
    aplicacion pide EL SUYO, el del contrato, y no un 8765 comun. Con el 8765 comun,
    abrir dos tableros por doble clic mandaba el segundo a un puerto al azar, y ninguno
    de los dos lo reconocia CriticidadCHEC, que los busca donde dice el contrato.

    `menu` es la URL de CriticidadCHEC cuando fue el quien lanzo este tablero. Con
    ella, el armazon sale con la barra de "Volver al menu" / "Cerrar" en vez del boton
    de cerrar suelto. Los dos apagan SOLO este tablero: apagarlo todo es cosa del menu.

    `app` es la CARPETA de la aplicacion -- `carpeta` es solo su panel --, y con ella
    este servidor deja su pid escrito y se rinde cuando su puerto ya lo tiene esa misma
    aplicacion, en vez de servir una segunda copia en un puerto al azar. Sin `app` se
    comporta como siempre, que es lo que necesitan las pruebas y cualquier uso suelto.

    Devuelve el codigo con el que hay que salir.
    """
    if app is not None:
        codigo = revisar_puerto(app, puerto or preferido, abrir=abrir)
        if codigo is not None:
            return codigo

    piezas = _catalogo(carpeta)
    if menu:
        armazon = piezas["/index.html"]
        piezas["/index.html"] = piezas["/"] = _Pieza(
            armazon.ruta, inmutable=False,
            datos=_con_barra_de_menu(armazon.ruta.read_bytes(), menu))
    manejador = type("Manejador", (_Manejador,), {
        "piezas": piezas,
        "silencioso": not verboso,
    })
    puerto = puerto or puerto_libre(preferido)

    # Solo 127.0.0.1: la aplicacion es local y no tiene ninguna autenticacion, asi que
    # escuchar en 0.0.0.0 la publicaria a toda la red de la oficina sin decirlo.
    with _Servidor(("127.0.0.1", puerto), manejador) as servidor:
        # El pid se escribe con el socket YA atado: antes, un arranque que fallara al
        # atarse dejaria un archivo apuntando a un proceso que nunca sirvio nada.
        if app is not None:
            escribir_pid(app)
        url = f"http://127.0.0.1:{puerto}/"
        print(f"\n  Tablero servido en  {url}")
        if abrir:
            # En un hilo aparte: lanzar el navegador tarda un momento, y sin esto su
            # primera peticion podria llegar antes de que el servidor este atendiendo.
            def _abrir() -> None:
                if not abrir_navegador(url):
                    # Decirlo. El fallo silencioso aqui deja al usuario mirando una
                    # ventana de terminal sin saber que el tablero ya esta listo.
                    print(f"  No se pudo abrir el navegador solo: copia {url} y pegalo.")

            threading.Timer(0.3, _abrir).start()
        print("  Deja esta ventana abierta mientras lo usas. Ctrl+C para detenerlo.\n")
        try:
            servidor.serve_forever()
            # Se llega aqui cuando el boton de cerrar del tablero llamo a `shutdown()`.
            # Ctrl+C no pasa por aqui: sale por la excepcion de abajo.
            print("  Cerrado desde el tablero.")
        except KeyboardInterrupt:
            print("\n  Detenido.")
        finally:
            # Pase lo que pase: un pid olvidado apunta tarde o temprano a otro proceso,
            # y la siguiente apertura lo leeria como "esta aplicacion ya esta abierta"
            # sobre un puerto que tiene cualquier otra cosa.
            if app is not None:
                borrar_pid(app)
    return 0
