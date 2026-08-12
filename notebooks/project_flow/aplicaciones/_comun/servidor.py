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

# Un ano. Solo se aplica a archivos cuyo nombre contiene el hash de su contenido:
# si cambian, cambia la URL, asi que no hay forma de servir algo viejo.
_CACHE_INMUTABLE = "public, max-age=31536000, immutable"
# El armazon no lleva hash -- es la URL de entrada --, asi que se revalida siempre.
# Con ETag, revalidar cuesta un 304 de cero bytes cuando no cambio.
_CACHE_REVALIDAR = "no-cache"


class _Pieza:
    __slots__ = ("ruta", "tipo", "cache", "etag", "gz", "tam")

    def __init__(self, ruta: Path, inmutable: bool):
        self.ruta = ruta
        tipo, _ = mimetypes.guess_type(ruta.name)
        self.tipo = tipo or "application/octet-stream"
        self.cache = _CACHE_INMUTABLE if inmutable else _CACHE_REVALIDAR
        datos = ruta.read_bytes()
        self.tam = len(datos)
        self.etag = f'"{hash((ruta.name, self.tam)) & 0xFFFFFFFF:08x}"'
        # Solo el comprimido queda en memoria (6,5 MB para el tablero mas pesado).
        # El crudo se lee de disco si algun cliente no acepta gzip, que en la practica
        # no pasa: todos los navegadores desde 2010 lo anuncian.
        gz = ruta.parent / f"{ruta.name}.gz"
        self.gz = gz.read_bytes() if gz.exists() else gzip.compress(datos, 6, mtime=0)


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


class _Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    piezas: dict[str, _Pieza] = {}
    silencioso = True

    def do_GET(self) -> None:  # noqa: N802 -- nombre impuesto por BaseHTTPRequestHandler
        self._responder(cuerpo=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._responder(cuerpo=False)

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
        datos = pieza.gz if acepta_gzip else pieza.ruta.read_bytes()

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


class _Servidor(socketserver.ThreadingTCPServer):
    # Sin esto, cerrar y volver a abrir la aplicacion en menos de dos minutos falla
    # con "Address already in use" por el TIME_WAIT del socket anterior.
    allow_reuse_address = True
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


def puerto_libre(preferido: int = 8765) -> int:
    """Devuelve `preferido` si esta libre; si no, uno que el sistema asigne."""
    for candidato in (preferido, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", candidato))
            except OSError:
                continue
            return s.getsockname()[1]
    raise SystemExit("No se pudo reservar ningun puerto local.")


def servir(carpeta: Path, *, abrir: bool = True, puerto: int | None = None,
           verboso: bool = False) -> None:
    """Sirve `carpeta` en 127.0.0.1 hasta que se interrumpa con Ctrl+C."""
    manejador = type("Manejador", (_Manejador,), {
        "piezas": _catalogo(carpeta),
        "silencioso": not verboso,
    })
    puerto = puerto or puerto_libre()

    # Solo 127.0.0.1: la aplicacion es local y no tiene ninguna autenticacion, asi que
    # escuchar en 0.0.0.0 la publicaria a toda la red de la oficina sin decirlo.
    with _Servidor(("127.0.0.1", puerto), manejador) as servidor:
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
        except KeyboardInterrupt:
            print("\n  Detenido.")
