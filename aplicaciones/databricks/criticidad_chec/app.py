"""CriticidadCHEC en Databricks: los cuatro tableros estaticos bajo un solo dominio.

## Por que una app y no cuatro

Habia una Databricks App por tablero, y cuatro comandos que las publicaban. El
workspace **topa en tres apps** (contrato D5), asi que la cuarta no cabia nunca: el
orquestador tenia una tabla de prioridad y dejaba `03` y `04` sin desplegar. Ademas
cada una repetia el mismo andamio -- `app.yaml`, `requirements.txt`, un `app.py` que
lee del Volume -- con diferencias que solo existian por como habia crecido cada una.

Una sola app con cuatro rutas gasta **un** cupo, deja de necesitar la tabla de
prioridad, y hace que el usuario no tenga que recordar cuatro URLs.

El simulador se queda aparte, y no por tamanio: necesita un kernel de Python vivo para
que "Simular" corra el modelo MIL. Esto sirve archivos.

## Que sirve, exactamente

Cada tablero se construye ANTES de desplegar -- `chec_tableros.<modulo>.construir()`,
el mismo codigo que corre la aplicacion de escritorio -- y se empaqueta con
`aplicaciones/_comun/empaquetar.py`. Eso deja una carpeta por tablero:

    index.html + index.html.gz
    plotly-<version>.<hash>.js + .gz
    datos.<hash>.json + .gz
    manifiesto.json

Esta app sube esas carpetas tal cual y las sirve. **No genera nada**, no abre el CSV y
no necesita un cluster: por eso arranca en segundos y no en minutos.

Que las piezas lleven el hash del contenido en el nombre no es decoracion: permite
`Cache-Control: immutable`, y con eso la segunda apertura de un tablero de 29 MB
transfiere los 20 KB del `index.html` y nada mas.

## El Volume se lee por la Files API, no por FUSE

`/Volumes/...` NO esta montado dentro del contenedor de una app -- da 403, medido
(contrato D2). `w.files.download` va por la Files API de Unity Catalog y si funciona
desde el service principal. Es la misma decision que ya tomaron las apps de un solo
tablero, y la unica forma de leer el Volume desde aqui.
"""
from __future__ import annotations

import gzip
import json
import os

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

import catalogo as _catalogo
import pagina as _pagina

# La carpeta del Volume donde `/subir-a-databricks` dejo los paneles. Entra por
# entorno porque el catalogo y el esquema se RESUELVEN en cada despliegue (contrato C):
# `workspace.default` no existe en todos los workspaces, y el de CHEC es uno de los que
# no lo tiene (D1).
RAIZ_PANELES = os.environ.get(
    "RAIZ_PANELES",
    "/Volumes/workspace/default/chec-simulador/paneles",
)

# Tipo de contenido por extension. Corto a proposito: lo que empaqueta un tablero son
# tres formas y nada mas, y una tabla mas larga invitaria a servir cosas que este
# directorio no deberia contener.
TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

app = FastAPI(title="CriticidadCHEC")

# `ruta completa en el Volume -> bytes`. Se llena bajo demanda y no se vacia: los
# nombres llevan hash, asi que una pieza cacheada no puede quedar obsoleta -- un
# tablero reconstruido cambia el NOMBRE de sus piezas, no su contenido. El unico
# archivo sin hash es `index.html`, y para ese esta `?refresh=1`.
_cache: dict[str, bytes] = {}


def _descargar(ruta: str) -> bytes:
    """Los bytes de una pieza, del cache o del Volume.

    Los dos modos de fallo se separan a proposito, porque desde el navegador se ven
    igual -- una pagina que no carga -- y se arreglan de formas opuestas:

      * **404**: la pieza no esta. O la URL esta mal escrita, o ese tablero no se
        llego a construir en el ultimo despliegue (el comando lo marca `degradado` y
        sigue con los demas, en vez de publicar un panel viejo).
      * **502**: el Volume no se dejo leer. Casi siempre es que al service principal
        de la app le falta `READ VOLUME` -- el grant que `uc_securable` aplica solo si
        quien despliega tiene `USE CATALOG` (contrato D3).
    """
    if ruta not in _cache:
        try:
            _cache[ruta] = WorkspaceClient().files.download(ruta).contents.read()
        except NotFound as exc:
            raise HTTPException(
                status_code=404,
                detail=(f"No existe {ruta} en el Volume. Si la URL es correcta, ese "
                        "tablero no se construyo en el ultimo despliegue: revisa la "
                        "bitacora de la corrida."),
            ) from exc
        except Exception as exc:  # noqa: BLE001 -- el motivo real viaja al usuario
            raise HTTPException(
                status_code=502,
                detail=(f"No se pudo leer {ruta} del Volume: {exc}. Suele ser que al "
                        "service principal de la app le falta READ VOLUME sobre "
                        "el Volume (contrato D3)."),
            ) from exc
    return _cache[ruta]


def _servir(ruta_volumen: str, nombre: str, request: Request) -> Response:
    """Una pieza del panel, en gzip si el navegador lo acepta.

    El `.gz` se sube ya comprimido junto a su original: comprimir aqui costaria
    recomprimir 29 MB en cada peticion, que es justo lo que `GZipMiddleware` hace y
    por lo que no se usa.
    """
    tipo = TIPOS.get("." + nombre.rsplit(".", 1)[-1].lower())
    if tipo is None:
        raise HTTPException(status_code=404, detail=f"{nombre}: tipo no servible")

    cabeceras = {"Vary": "Accept-Encoding"}
    # `immutable` solo donde es cierto. `index.html` no lleva hash y es lo que cambia
    # cuando se reconstruye un tablero; decirle al navegador que no cambia nunca seria
    # publicar una version nueva que nadie llega a ver.
    if nombre != "index.html":
        cabeceras["Cache-Control"] = "public, max-age=31536000, immutable"

    if "gzip" in request.headers.get("accept-encoding", ""):
        cabeceras["Content-Encoding"] = "gzip"
        return Response(content=_descargar(f"{ruta_volumen}/{nombre}.gz"),
                        media_type=tipo, headers=cabeceras)
    return Response(content=_descargar(f"{ruta_volumen}/{nombre}"),
                    media_type=tipo, headers=cabeceras)


@app.get("/salud", response_class=PlainTextResponse)
def salud() -> str:
    """A proposito NO toca el Volume.

    Separa "la app esta rota" de "falta el permiso sobre el Volume", que desde el
    navegador se ven igual: las dos son una pagina que no carga.
    """
    return "ok"


@app.get("/", response_class=HTMLResponse)
def raiz() -> str:
    return _pagina.portada(_catalogo.RUTAS)


@app.get("/tableros")
def tableros() -> dict:
    """Que hay publicado, en JSON. Util para comprobar un despliegue sin abrir nada."""
    return {"raiz_paneles": RAIZ_PANELES,
            "tableros": [{"clave": r.clave, "ruta": r.ruta, "titulo": r.titulo}
                         for r in _catalogo.RUTAS]}


def _registrar(ruta_publica: str, clave: str) -> None:
    """Le cuelga a un tablero sus dos rutas: la del documento y la de sus piezas.

    Se hace en un bucle y no escribiendo cuatro pares de funciones porque los cuatro
    tableros se sirven exactamente igual. Lo que cambia entre ellos es una cadena.
    """
    carpeta = f"{RAIZ_PANELES}/{clave}"

    @app.get(ruta_publica, response_class=Response, name=f"panel_{clave}")
    def _documento(request: Request, refresh: int = 0) -> Response:
        if refresh:
            # Solo el `index.html` de ESTE tablero: un `?refresh=1` que vaciara el
            # cache entero obligaria a redescargar los 29 MB de los otros tres.
            _cache.pop(f"{carpeta}/index.html", None)
            _cache.pop(f"{carpeta}/index.html.gz", None)
        return _servir(carpeta, "index.html", request)

    @app.get(f"{ruta_publica}/{{pieza}}", response_class=Response,
             name=f"pieza_{clave}")
    def _pieza(pieza: str, request: Request) -> Response:
        # Sin barras ni `..`: las piezas viven en la carpeta del tablero y en ninguna
        # otra. El nombre viene del `index.html` que empaquetamos nosotros, pero la
        # ruta la escribe quien pida, y eso basta para comprobarlo.
        if "/" in pieza or pieza.startswith("."):
            raise HTTPException(status_code=404, detail=pieza)
        return _servir(carpeta, pieza, request)


for _ruta in _catalogo.RUTAS:
    _registrar(_ruta.ruta, _ruta.clave)
