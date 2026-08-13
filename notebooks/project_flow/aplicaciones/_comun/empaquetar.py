"""Parte el HTML autocontenido de un cuaderno en piezas que el navegador cachea.

## El problema

Los cuadernos 01 y 02 escriben un documento UNICO con todo adentro: plotly.js, los
datos de los 208 circuitos y la logica del panel. Medido sobre `reports/paneles/`:

| pieza                | 01 clima  | 02 vanos |
|----------------------|-----------|----------|
| plotly.js v3.6.0     |  4,62 MB  |  4,62 MB |
| datos del panel (CTX)| 23,12 MB  |  1,41 MB |
| armazon + figura     |    64 KB  |    53 KB |
| **total**            | **27,8 MB** | **6,1 MB** |

Servido asi, el navegador vuelve a bajar y a *reinterpretar* los 27,8 MB en cada
apertura, y los datos llegan como un literal de JavaScript dentro de un `<script>`,
que el motor tiene que parsear como codigo.

## Lo que hace este modulo

Tres cambios, ninguno toca la logica del panel:

1. **plotly.js sale a su propio archivo**, con el numero de version y un hash en el
   nombre. Es byte por byte el mismo en las dos aplicaciones, asi que se descarga
   una vez y se sirve `immutable`: la segunda apertura no lo vuelve a pedir.
2. **Los datos salen a un `.json`**, tambien con hash en el nombre. Ademas de
   cachearse, pasan a leerse con `JSON.parse` nativo en vez de parsearse como
   codigo fuente.
3. **Se deja al lado la version `.gz`** de cada pieza, comprimida en tiempo de
   construccion con nivel 9. El servidor la entrega tal cual, sin gastar CPU por
   peticion.

El armazon (`index.html`) queda en decenas de KB y es lo unico que se revalida.

## Lo que NO hace

No reescribe una sola linea de la logica del panel. El IIFE original se conserva
intacto: lo unico que cambia es de donde sale `CTX`, y eso queda envuelto en el
`fetch` que trae el JSON. Si el panel del cuaderno cambia, esto sigue funcionando.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# La ruta del apagado se toma del servidor que la atiende, no se repite aqui: si los
# dos extremos no coinciden, el boton contesta 404 y no apaga nada.
from servidor import RUTA_APAGADO as _RUTA_APAGADO

# `include_plotlyjs=True` de plotly incrusta la libreria como primer <script> del
# documento y la abre siempre con este banner de licencia. Es la marca que permite
# reconocerla sin adivinar por tamano.
_BANNER_PLOTLY = re.compile(r"/\*\*\s*\n\s*\*\s*plotly\.js v(?P<version>[0-9][^\s*]*)")
_APERTURA_SCRIPT = re.compile(r"<script[^>]*>")
_ASIGNACION_CTX = "var CTX = "

# Nivel 9 y no 6: comprimir es un costo de construccion que se paga UNA vez, y el
# archivo resultante se sirve miles de veces. Medido sobre el CTX de 01, la
# diferencia entre 6 y 9 son unos segundos de construccion.
_NIVEL_GZIP = 9


@dataclass
class Pieza:
    nombre: str
    bytes_crudos: int
    bytes_gzip: int


@dataclass
class Paquete:
    destino: Path
    version_plotly: str
    piezas: list[Pieza] = field(default_factory=list)

    @property
    def total_crudo(self) -> int:
        return sum(p.bytes_crudos for p in self.piezas)

    @property
    def total_gzip(self) -> int:
        return sum(p.bytes_gzip for p in self.piezas)

    def resumen(self) -> str:
        lineas = [f"{'pieza':<34}{'crudo':>12}{'gzip':>12}"]
        for p in self.piezas:
            lineas.append(
                f"{p.nombre:<34}{p.bytes_crudos / 1024**2:>9,.2f} MB"
                f"{p.bytes_gzip / 1024**2:>9,.2f} MB"
            )
        lineas.append(
            f"{'TOTAL':<34}{self.total_crudo / 1024**2:>9,.2f} MB"
            f"{self.total_gzip / 1024**2:>9,.2f} MB"
        )
        return "\n".join(lineas)


def _hash_corto(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()[:10]


def _escribir(destino: Path, nombre: str, contenido: bytes, *, comprimir: bool) -> Pieza:
    (destino / nombre).write_bytes(contenido)
    tam_gz = 0
    if comprimir:
        # `mtime=0` para que el .gz sea reproducible: sin eso, dos construcciones de
        # los mismos bytes dan archivos distintos y cualquier comparacion posterior
        # (rsync, hash, revision de cambios) reporta diferencias que no existen.
        comprimido = gzip.compress(contenido, _NIVEL_GZIP, mtime=0)
        (destino / f"{nombre}.gz").write_bytes(comprimido)
        tam_gz = len(comprimido)
    return Pieza(nombre=nombre, bytes_crudos=len(contenido), bytes_gzip=tam_gz)


def _extraer_plotly(html: str) -> tuple[str, str, str]:
    """Devuelve (html sin plotly con un marcador, codigo de plotly, version)."""
    banner = _BANNER_PLOTLY.search(html)
    if banner is None:
        raise ValueError(
            "El documento no trae plotly.js incrustado. El cuaderno tiene que "
            "exportarse con include_plotlyjs=True; sin la libreria adentro no hay "
            "nada que separar."
        )
    version = banner.group("version")

    # El <script> que la contiene es el que abre inmediatamente antes del banner.
    apertura = None
    for m in _APERTURA_SCRIPT.finditer(html, 0, banner.start()):
        apertura = m
    if apertura is None:
        raise ValueError("Se encontro el banner de plotly.js pero no su etiqueta <script>.")
    fin = html.find("</script>", apertura.end())
    if fin < 0:
        raise ValueError("El <script> de plotly.js no cierra.")

    codigo = html[apertura.end():fin]
    marcador = "<!--PLOTLY-->"
    resto = html[:apertura.start()] + marcador + html[fin + len("</script>"):]
    return resto, codigo, version


def _extraer_ctx(html: str, archivo_ctx: str) -> tuple[str, str]:
    """Saca el literal `var CTX = {...}` y lo reemplaza por una carga con fetch.

    El IIFE del panel no se toca: se conserva completo y solo se envuelve en la
    continuacion del fetch. Esto es lo que hace que el empaquetador sobreviva a
    cambios en la logica del panel.
    """
    i = html.find(_ASIGNACION_CTX)
    if i < 0:
        raise ValueError("El documento no declara `var CTX = ...`; no es un panel de 01/02.")

    inicio_valor = i + len(_ASIGNACION_CTX)
    # `raw_decode` encuentra el final EXACTO del valor JSON. Buscar el `};` a mano
    # fallaria: el propio JSON contiene esa secuencia dentro de las cadenas.
    _, fin_valor = json.JSONDecoder().raw_decode(html, inicio_valor)
    ctx_json = html[inicio_valor:fin_valor]

    apertura = None
    for m in _APERTURA_SCRIPT.finditer(html, 0, i):
        apertura = m
    if apertura is None:
        raise ValueError("Se encontro `var CTX` pero no su etiqueta <script>.")
    fin_script = html.find("</script>", fin_valor)
    if fin_script < 0:
        raise ValueError("El <script> del panel no cierra.")

    cuerpo = html[apertura.end():fin_script]
    # Unico cambio dentro del cuerpo: el origen de CTX.
    cuerpo_sin_datos = cuerpo.replace(
        _ASIGNACION_CTX + ctx_json + ";", "var CTX = window.__CTX__;", 1
    )
    if cuerpo_sin_datos == cuerpo:
        raise ValueError("No se pudo sustituir la asignacion de CTX en el cuerpo del panel.")

    nuevo_script = _PLANTILLA_CARGA.replace("__ARCHIVO_CTX__", archivo_ctx).replace(
        "__CUERPO__", cuerpo_sin_datos
    )
    resto = html[:apertura.end()] + nuevo_script + html[fin_script:]
    return resto, ctx_json


# El `catch` no es decorativo. Abrir `index.html` con doble clic (protocolo file://)
# hace que `fetch` falle por CORS en Chrome y en Edge, el panel quede mudo y la
# figura se vea bien pero no responda a ningun control -- el modo de fallo mas
# desconcertante posible. Aqui se detecta y se dice en pantalla.
_PLANTILLA_CARGA = """
(function () {
  function aviso(texto) {
    var caja = document.createElement('div');
    caja.setAttribute('role', 'alert');
    caja.style.cssText = 'margin:12px;padding:12px 16px;border:1px solid #c62828;' +
      'border-radius:6px;background:#fff5f5;color:#7f1d1d;font:14px/1.5 system-ui,sans-serif;';
    caja.textContent = texto;
    document.body.insertBefore(caja, document.body.firstChild);
  }
  if (location.protocol === 'file:') {
    aviso('Este tablero se tiene que abrir desde el servidor local, no con doble clic ' +
          'sobre el archivo: los datos se cargan aparte y el navegador bloquea esa lectura ' +
          'sobre file://. Cierra esta pestana y usa iniciar.command (macOS) o iniciar.bat (Windows).');
    return;
  }
  fetch('__ARCHIVO_CTX__').then(function (r) {
    if (!r.ok) { throw new Error('HTTP ' + r.status + ' al pedir __ARCHIVO_CTX__'); }
    return r.json();
  }).then(function (datos) {
    window.__CTX__ = datos;
__CUERPO__
  }).catch(function (e) {
    aviso('No se pudieron cargar los datos del tablero (__ARCHIVO_CTX__): ' + e.message);
  });
})();
"""


def empaquetar(html: str, destino: Path, *, titulo: str) -> Paquete:
    """Parte `html` en armazon + plotly.js + datos, todo bajo `destino`."""
    destino.mkdir(parents=True, exist_ok=True)
    for viejo in destino.glob("*"):
        if viejo.is_file():
            viejo.unlink()

    sin_plotly, codigo_plotly, version = _extraer_plotly(html)

    # El nombre lleva hash porque de eso depende poder servirlo como `immutable`: si
    # el contenido cambia, cambia el nombre, y el navegador pide el nuevo sin que
    # nadie tenga que acordarse de invalidar nada.
    bytes_plotly = codigo_plotly.encode("utf-8")
    nombre_plotly = f"plotly-{version}.{_hash_corto(bytes_plotly)}.js"

    # El nombre del CTX se conoce antes de tener su contenido, asi que se hace en dos
    # pasos: primero se extrae con un nombre provisional, despues se renombra.
    sin_datos, ctx_json = _extraer_ctx(sin_plotly, "__CTX_PENDIENTE__")
    bytes_ctx = ctx_json.encode("utf-8")
    nombre_ctx = f"datos.{_hash_corto(bytes_ctx)}.json"
    sin_datos = sin_datos.replace("__CTX_PENDIENTE__", nombre_ctx)

    armazon = sin_datos.replace(
        "<!--PLOTLY-->",
        f'<script src="{nombre_plotly}"></script>',
        1,
    )
    armazon = _ajustar_titulo(armazon, titulo)
    armazon = _inyectar_boton_cerrar(armazon)

    paquete = Paquete(destino=destino, version_plotly=version)
    paquete.piezas.append(_escribir(destino, "index.html", armazon.encode("utf-8"), comprimir=True))
    paquete.piezas.append(_escribir(destino, nombre_plotly, bytes_plotly, comprimir=True))
    paquete.piezas.append(_escribir(destino, nombre_ctx, bytes_ctx, comprimir=True))

    (destino / "manifiesto.json").write_text(
        json.dumps(
            {
                "titulo": titulo,
                "version_plotly": version,
                "piezas": [
                    {"nombre": p.nombre, "bytes": p.bytes_crudos, "bytes_gzip": p.bytes_gzip}
                    for p in paquete.piezas
                ],
                "total_bytes": paquete.total_crudo,
                "total_bytes_gzip": paquete.total_gzip,
            },
            indent=1,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return paquete


def _ajustar_titulo(html: str, titulo: str) -> str:
    return re.sub(r"<title>.*?</title>", f"<title>{titulo}</title>", html, count=1, flags=re.S)


# Boton de cerrar. Apaga el servidor que sirve ESTE tablero -- no los otros, que corren
# en su propio proceso y su propio puerto.
#
# Despues de apagar NO se intenta `window.close()` a secas y ya: el navegador solo deja
# cerrar por script las ventanas que abrio un script, y estas las abrio el sistema, asi
# que la llamada se ignora en silencio y el usuario se queda mirando una pagina que
# parece viva. Se intenta igual -- por si acaso --, y si sigue ahi al medio segundo se
# tapa todo con un aviso que dice que ya se puede cerrar la pestana. Eso es honesto:
# el servidor SI murio, lo unico que no se puede es cerrar la pestana por decreto.
_BOTON_CERRAR = """
<div id="cerrar-tablero" style="position:fixed;top:10px;right:12px;z-index:9999;">
  <button type="button" title="Detiene el servidor de este tablero"
    style="font:13px/1 system-ui,-apple-system,'Segoe UI',sans-serif;padding:7px 13px;
           border:1px solid #c62828;border-radius:6px;background:#fff;color:#c62828;
           cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.18);">Cerrar tablero</button>
</div>
<script>
(function () {
  var caja = document.getElementById('cerrar-tablero');
  caja.querySelector('button').addEventListener('click', function () {
    if (!window.confirm('Se detiene el servidor de este tablero. Para volver a abrirlo hay que iniciarlo de nuevo.')) { return; }
    fetch('__RUTA__', { method: 'POST' }).catch(function () {
      // El servidor puede morir antes de contestar; eso es exito, no fallo.
    }).then(function () {
      caja.remove();
      window.close();
      setTimeout(function () {
        document.body.innerHTML =
          '<div style="font:16px/1.6 system-ui,-apple-system,sans-serif;padding:40px;' +
          'max-width:640px;margin:0 auto;color:#2b2b2b;">' +
          '<h1 style="font-size:20px;margin:0 0 12px;">Tablero cerrado</h1>' +
          '<p>El servidor se detuvo. El navegador no permite cerrar por si sola una ' +
          'pestana que no abrio un script, asi que cierrala tu.</p>' +
          '<p style="color:#666;">Para volver a abrirlo: <code>iniciar.command</code> ' +
          '(macOS) o <code>iniciar.bat</code> (Windows).</p></div>';
      }, 500);
    });
  });
})();
</script>
"""


def _inyectar_boton_cerrar(html: str) -> str:
    marca = "</body>"
    if marca not in html:
        raise ValueError("El documento no tiene </body>; no se pudo insertar el boton de cerrar.")
    boton = _BOTON_CERRAR.replace("__RUTA__", _RUTA_APAGADO)
    return html.replace(marca, boton + marca, 1)
