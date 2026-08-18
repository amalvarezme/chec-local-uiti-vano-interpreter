"""Conducir un tablero con Chrome de verdad, y hacerle lo que le hace el usuario.

Estaba dentro de `ayudas_simulador.py`, que es el arnes del simulador. Sale de ahi
porque el navegador no tiene nada de simulador: los cuatro tableros estaticos se
conducen igual, y la pregunta que motivo este modulo -- "si me voy a otro programa y
vuelvo, ¿el tablero sigue respondiendo?" -- se le hace a los cinco.

Lo que aporta sobre `Runtime.evaluate` a secas son los tres gestos que NO se pueden
imitar escribiendo JavaScript, porque los hace el navegador por su cuenta:

  * `congelar`: Chrome congela las pestanias que quedan de fondo. No es una pausa del
    JavaScript -- **cierra el WebSocket**, medido: al descongelar aparece en la consola
    `Connection lost, reconnecting in 0 seconds.`
  * `sin_red`: la tapa del portatil, el wifi que cambia de red. La pestania sigue
    montada y sus sockets se caen.
  * `espiar_consola`: el frontend de Jupyter avisa de que perdio la conexion por
    `console.warn` y por ningun otro sitio. Sin engancharla, una pestania muerta se
    lee exactamente igual que una viva.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Navegador:
    def __init__(self, carpeta: Path, ancho: int = 2000, alto: int = 1400):
        import websocket
        self._ws_mod = websocket
        self.puerto = puerto_libre()
        self.proceso = subprocess.Popen([
            str(CHROME), "--headless=new", "--disable-gpu", "--use-gl=swiftshader",
            "--enable-unsafe-swiftshader", "--no-sandbox",
            f"--remote-debugging-port={self.puerto}", "--remote-allow-origins=*",
            f"--user-data-dir={carpeta}", f"--window-size={ancho},{alto}",
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = None
        for _ in range(80):
            time.sleep(0.4)
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.puerto}/json/list") as r:
                    objetivos = json.load(r)
                # El PRIMERO de la lista no siempre es una pestania: puede ser el
                # propio navegador o una extension, y ese no acepta el tamanio de
                # pantalla -- responde "Target does not support metrics override",
                # que no dice en ningun lado que el problema sea a quien preguntas.
                paginas = [o for o in objetivos if o.get("type") == "page"
                           and o.get("webSocketDebuggerUrl")]
                if paginas:
                    url = paginas[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
        if url is None:
            self.proceso.kill()
            raise RuntimeError("Chrome no levanto")
        self.ws = websocket.create_connection(url, timeout=600)
        self.n = 0
        self.errores: list[str] = []
        self.cmd("Runtime.enable")
        self.cmd("Page.enable")
        # Para `sin_red`. Se habilita al arrancar y no en el gesto: activarlo con la
        # pagina ya montada deja fuera lo que la pagina pidio antes.
        self.cmd("Network.enable")
        # El ancho importa: el zoom de los mapas se calcula contra el tamanio del
        # subplot, asi que una ventana estrecha cambia lo que se esta midiendo.
        self.cmd("Emulation.setDeviceMetricsOverride", width=ancho, height=alto,
                 deviceScaleFactor=1, mobile=False)

    def cmd(self, metodo: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": metodo, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                texto = msg["params"].get("exceptionDetails", {}).get("text", "")
                self.errores.append(str(texto)[:200])
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{metodo}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True,
                     awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return r["result"].get("value")

    def cerrar(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
        self.proceso.kill()


# ------------------------------------------------------- irse y volver a la pestania

# Cuanto se espera despues de descongelar o de recuperar la red. Los reintentos del
# frontend de Jupyter van con espera creciente al azar -- `0..2^n-1` segundos, siete
# intentos --, asi que preguntar en el acto mide la espera del reintento y no si el
# tablero volvio.
GRACIA = 90.0


def congelar(nav: Navegador, segundos: float, gracia: float = 5.0) -> None:
    """Congela la pestania como hace Chrome con la que queda de fondo, y la despierta.

    `Page.setWebLifecycleState` es el mismo mecanismo del navegador, no una
    imitacion: `frozen` es el estado al que Chrome lleva una pestania de fondo.
    """
    nav.cmd("Page.setWebLifecycleState", state="frozen")
    time.sleep(segundos)
    nav.cmd("Page.setWebLifecycleState", state="active")
    time.sleep(gracia)


def sin_red(nav: Navegador, segundos: float, gracia: float = GRACIA) -> None:
    """Deja la pestania sin red el rato que se le diga, y despues espera la vuelta."""
    nav.cmd("Network.emulateNetworkConditions", offline=True, latency=0,
            downloadThroughput=-1, uploadThroughput=-1)
    time.sleep(segundos)
    nav.cmd("Network.emulateNetworkConditions", offline=False, latency=0,
            downloadThroughput=-1, uploadThroughput=-1)
    time.sleep(gracia)


_ESPIA_CONSOLA = """
(function () {
  if (window.__avisos) { return 'ya'; }
  window.__avisos = [];
  ['warn', 'error'].forEach(function (nivel) {
    var orig = console[nivel];
    console[nivel] = function () {
      window.__avisos.push(nivel + ': ' + Array.prototype.join.call(arguments, ' '));
      return orig.apply(console, arguments);
    };
  });
  return 'puesto';
})()
"""


def espiar_consola(nav: Navegador) -> None:
    """Engancha `console.warn` y `console.error`. Hay que repetirlo tras cada recarga.

    Es la unica via para ver que el frontend perdio el kernel: lo dice por consola
    -- `Connection lost, reconnecting in N seconds.` -- y por ningun otro sitio.
    """
    nav.js(_ESPIA_CONSOLA)


def avisos(nav: Navegador) -> list[str]:
    try:
        return nav.js("(window.__avisos || []).slice(-25)") or []
    except Exception:
        return []
