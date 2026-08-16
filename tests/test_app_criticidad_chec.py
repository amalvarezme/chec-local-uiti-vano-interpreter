"""La app consolidada de Databricks: cuatro tableros bajo un dominio.

## Por que esto existe como codigo del repositorio y no dentro de un comando

Las cinco apps de Databricks anteriores tenian su `app.py` escrito DENTRO de un bloque
de codigo de un `.md`, para que el asistente lo copiara a un directorio temporal al
desplegar. Ese diseno es exactamente el que este cambio esta retirando en todas
partes: codigo que ninguna herramienta ve, que no compila en su archivo, que no se
puede importar y cuyo unico modo de fallar es en produccion.

Aqui vive en `aplicaciones/databricks/criticidad_chec/` y se prueba como cualquier
otra cosa. Lo unico que el comando hace con el es subirlo.

## Lo que estas pruebas NO pueden decir

No hay Databricks. `files.download` se sustituye por una lectura de disco, asi que lo
que se comprueba es el ENRUTADO, la negociacion de gzip y las cabeceras de cache. Que
el Volume se deje leer de verdad, que el grant este puesto y que la app arranque en el
contenedor son cosas de una corrida real, y por eso el comando exige una bitacora.
"""
from __future__ import annotations

import gzip
import importlib
import sys
import types
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "aplicaciones" / "databricks" / "criticidad_chec"
COMUN = RAIZ / "aplicaciones" / "_comun"

fastapi = pytest.importorskip(
    "fastapi",
    reason="la app consolidada corre en Databricks, no en el entorno del repositorio")


PIEZA_CON_HASH = "datos.abc123.json"


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """La app montada sobre un Volume de mentira."""
    for tablero in ("clima", "agrupamiento", "trayectorias_circuitos",
                    "trayectorias_vanos"):
        carpeta = tmp_path / tablero
        carpeta.mkdir()
        cuerpo = f"<html><body>panel de {tablero}</body></html>".encode()
        (carpeta / "index.html").write_bytes(cuerpo)
        (carpeta / "index.html.gz").write_bytes(gzip.compress(cuerpo, 6))
        (carpeta / PIEZA_CON_HASH).write_bytes(b'{"x":1}')
        (carpeta / f"{PIEZA_CON_HASH}.gz").write_bytes(gzip.compress(b'{"x":1}', 6))

    monkeypatch.setenv("RAIZ_PANELES", str(tmp_path))
    monkeypatch.syspath_prepend(str(COMUN))
    monkeypatch.syspath_prepend(str(APP))

    # `databricks-sdk` es dependencia de la APP, no del repositorio. Se sustituye por
    # un doble que lee del disco: lo que se prueba aqui es todo lo que hay ENCIMA de
    # esa llamada.
    class _NoEncontrado(Exception):
        pass

    class _Cliente:
        def __init__(self):
            self.files = self

        def download(self, ruta):
            camino = Path(ruta)
            if not camino.is_file():
                raise _NoEncontrado(ruta)
            datos = camino.read_bytes()
            return types.SimpleNamespace(
                contents=types.SimpleNamespace(read=lambda: datos))

    sdk = types.ModuleType("databricks.sdk")
    sdk.WorkspaceClient = _Cliente
    errores = types.ModuleType("databricks.sdk.errors")
    errores.NotFound = _NoEncontrado
    monkeypatch.setitem(sys.modules, "databricks", types.ModuleType("databricks"))
    monkeypatch.setitem(sys.modules, "databricks.sdk", sdk)
    monkeypatch.setitem(sys.modules, "databricks.sdk.errors", errores)

    # `tableros.py` viaja copiado dentro de la app; aqui basta con que `_comun` este
    # en el path, que es lo que hace `syspath_prepend` de arriba.
    for modulo in ("app", "catalogo", "pagina"):
        sys.modules.pop(modulo, None)
    aplicacion = importlib.import_module("app")

    from fastapi.testclient import TestClient

    yield TestClient(aplicacion.app)

    for modulo in ("app", "catalogo", "pagina", "tableros"):
        sys.modules.pop(modulo, None)


RUTAS = ("/clima", "/agrupamiento", "/trayectorias-circuitos", "/trayectorias-vanos")


def test_la_salud_no_toca_el_volumen(cliente):
    """Separa "la app esta rota" de "falta el permiso sobre el Volume".

    Desde el navegador las dos se ven igual, y se arreglan de formas opuestas.
    """
    respuesta = cliente.get("/salud")
    assert respuesta.status_code == 200
    assert respuesta.text == "ok"


@pytest.mark.parametrize("ruta", RUTAS)
def test_cada_tablero_responde_en_su_ruta(ruta, cliente):
    assert cliente.get(ruta).status_code == 200


def test_el_simulador_no_tiene_ruta(cliente):
    """Y no es un olvido: necesita un interprete de Python vivo para correr el modelo
    MIL sobre lo que el usuario elija, y esta app sirve archivos."""
    assert cliente.get("/simulador").status_code == 404
    claves = [t["clave"] for t in cliente.get("/tableros").json()["tableros"]]
    assert "simulador" not in claves


def test_la_portada_nombra_los_cuatro_y_explica_la_ausencia_del_quinto(cliente):
    """Un menu que lista cuatro cuando el proyecto tiene cinco se lee como que falta
    uno. Decir por que no esta cuesta una frase."""
    texto = cliente.get("/").text
    for ruta in RUTAS:
        assert f'href="{ruta}"' in texto, f"la portada no enlaza {ruta}"
    assert "simulador" in texto.lower()


def test_los_titulos_salen_de_la_lista_compartida(cliente):
    """La portada y el menu local dicen lo MISMO de cada tablero.

    Los titulos estaban escritos dentro de `menu.catalogo()`; cuando aparecio este
    segundo consumidor se movieron a `aplicaciones/_comun/tableros.py`. Sin eso, el
    mismo tablero acaba con dos nombres segun por donde entre el usuario.
    """
    sys.path.insert(0, str(COMUN))
    try:
        tableros = importlib.import_module("tableros")
    finally:
        sys.path.pop(0)

    texto = cliente.get("/").text
    for tablero in tableros.ESTATICOS:
        assert tablero.titulo in texto, f"falta el titulo de {tablero.clave}"


@pytest.mark.parametrize("ruta", RUTAS)
def test_se_sirve_comprimido_a_quien_lo_acepta(ruta, cliente):
    """El `.gz` se sube ya comprimido junto a su original.

    Comprimir en cada peticion es lo que hace `GZipMiddleware`, y sobre los 29 MB del
    tablero del clima seria recomprimirlos en cada apertura.
    """
    con = cliente.get(ruta, headers={"accept-encoding": "gzip"})
    assert con.headers.get("content-encoding") == "gzip"
    sin = cliente.get(ruta, headers={"accept-encoding": "identity"})
    assert sin.headers.get("content-encoding") is None
    assert sin.status_code == 200


def test_solo_lo_que_lleva_hash_se_cachea_para_siempre(cliente):
    """`index.html` es lo unico sin hash, y es justo lo que cambia al reconstruir.

    Marcarlo `immutable` publicaria una version nueva que nadie llega a ver.
    """
    pieza = cliente.get(f"/clima/{PIEZA_CON_HASH}",
                        headers={"accept-encoding": "identity"})
    assert "immutable" in pieza.headers.get("cache-control", "")

    documento = cliente.get("/clima", headers={"accept-encoding": "identity"})
    assert "immutable" not in documento.headers.get("cache-control", "")


@pytest.mark.parametrize("pieza", ["../../etc/passwd", "..%2Fsecreto", ".oculto"])
def test_una_pieza_no_puede_salirse_de_su_carpeta(pieza, cliente):
    """El nombre lo escribe quien pida, no el `index.html` que empaquetamos."""
    assert cliente.get(f"/clima/{pieza}").status_code == 404


def test_una_pieza_que_no_existe_es_404_y_no_502(cliente):
    """Los dos fallos se ven igual desde el navegador y se arreglan al reves: uno es
    una URL mal escrita o un tablero sin construir, el otro es un grant que falta."""
    respuesta = cliente.get("/clima/no-existe.json")
    assert respuesta.status_code == 404
    assert "bitacora" in respuesta.json()["detail"]


def test_refrescar_un_tablero_no_tira_el_cache_de_los_otros(cliente):
    """Vaciar el cache entero obligaria a redescargar los 29 MB de los demas."""
    import app as aplicacion

    cliente.get("/clima", headers={"accept-encoding": "identity"})
    cliente.get("/agrupamiento", headers={"accept-encoding": "identity"})
    assert len(aplicacion._cache) == 2

    cliente.get("/clima?refresh=1", headers={"accept-encoding": "identity"})
    quedan = [k for k in aplicacion._cache if "agrupamiento" in k]
    assert quedan, "refrescar el clima se llevo por delante el cache del agrupamiento"


# ------------------------------------------------ lo que viaja al subir la app


def _empacador():
    import importlib.util

    ruta = RAIZ / "scripts" / "empacar_app_databricks.py"
    spec = importlib.util.spec_from_file_location("empacar_app_databricks", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_lo_que_se_sube_cubre_todo_lo_que_la_app_importa():
    """La guarda que impide subir una app incompleta.

    `catalogo.py` importa `tableros`, que NO vive en su carpeta: es de
    `aplicaciones/_comun/`, compartido con el menu local, y viaja copiado. El dia que
    alguien agregue un import a `app.py` sin agregarlo a la lista de archivos que se
    copian, la app sube entera y el contenedor no arranca -- un fallo que solo se ve
    en Databricks, con el despliegue ya hecho.

    Aqui se leen los imports de verdad, con `ast`, y se exige que cada uno sea o de la
    biblioteca estandar, o una dependencia declarada en `requirements.txt` de la app,
    o uno de los archivos que se copian.
    """
    import ast
    import sys as _sys

    empacador = _empacador()
    viajan = {n.removesuffix(".py")
              for n in empacador.ARCHIVOS_PROPIOS + empacador.ARCHIVOS_COMPARTIDOS}
    # El nombre que se instala y el que se importa no siempre coinciden. Solo hay un
    # caso aqui, y se escribe en vez de adivinarse con una regla: `databricks-sdk`
    # provee el paquete `databricks`.
    IMPORTA_COMO = {"databricks-sdk": "databricks"}
    declaradas = set()
    for linea in (APP / "requirements.txt").read_text("utf-8").splitlines():
        paquete = linea.split("#")[0].strip()
        if paquete:
            declaradas.add(IMPORTA_COMO.get(paquete, paquete.replace("-", "_")))

    faltan = []
    for nombre in sorted(empacador.ARCHIVOS_PROPIOS):
        if not nombre.endswith(".py"):
            continue
        arbol = ast.parse((APP / nombre).read_text("utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                modulos = [a.name.split(".")[0] for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0:
                modulos = [(nodo.module or "").split(".")[0]]
            else:
                continue
            for modulo in modulos:
                if (modulo in viajan or modulo in declaradas
                        or modulo in _sys.stdlib_module_names):
                    continue
                faltan.append(f"{nombre} importa {modulo!r}")

    assert not faltan, (
        "estos imports no viajan con la app ni estan declarados en su "
        f"requirements.txt:\n  " + "\n  ".join(faltan))


def test_preparar_la_fuente_sustituye_la_ruta_del_volumen(tmp_path):
    """Y es idempotente: cada pasada vuelve a copiar el `app.yaml` del repositorio y
    sustituye sobre esa copia limpia, no sobre el resultado de la anterior."""
    empacador = _empacador()
    empacador.preparar_fuente(tmp_path, raiz_paneles="/Volumes/x/y/chec/paneles")
    assert "/Volumes/x/y/chec/paneles" in (tmp_path / "app.yaml").read_text("utf-8")

    empacador.preparar_fuente(tmp_path, raiz_paneles="/Volumes/otro/z/chec/paneles")
    yaml = (tmp_path / "app.yaml").read_text("utf-8")
    assert "/Volumes/otro/z/chec/paneles" in yaml
    assert "/Volumes/x/y/chec/paneles" not in yaml


def test_una_sustitucion_que_no_encuentra_su_marca_aborta(tmp_path, monkeypatch):
    """No puede quedar en silencio: la app arrancaria apuntando al Volume de otro
    workspace, y eso se ve como "los cuatro tableros dan 502" -- que es exactamente el
    sintoma de un permiso que falta. Dos causas opuestas con la misma cara.
    """
    empacador = _empacador()
    monkeypatch.setattr(empacador, "MARCA_VOLUMEN", "/Volumes/marca/que/no/esta")
    with pytest.raises(SystemExit, match="Volume"):
        empacador.preparar_fuente(tmp_path, raiz_paneles="/Volumes/x/y/chec/paneles")


def test_subir_la_fuente_falla_si_le_falta_un_archivo(tmp_path, monkeypatch):
    """Mejor que subir una app sin su `catalogo.py` y descubrirlo cuando el contenedor
    no arranca."""
    empacador = _empacador()
    monkeypatch.setattr(empacador, "ARCHIVOS_PROPIOS",
                        (*empacador.ARCHIVOS_PROPIOS, "no_existe.py"))
    with pytest.raises(SystemExit, match="Falta"):
        empacador.preparar_fuente(tmp_path, raiz_paneles="/Volumes/x/y/chec/paneles")


def test_el_simulador_no_entra_en_los_paneles_que_se_construyen():
    """`ESTATICOS` es lo que la app publica, y el simulador no puede estar: un HTML no
    corre PyTorch."""
    sys.path.insert(0, str(COMUN))
    try:
        tableros = importlib.import_module("tableros")
    finally:
        sys.path.pop(0)
    assert [t.clave for t in tableros.ESTATICOS] == [
        "clima", "agrupamiento", "trayectorias_circuitos", "trayectorias_vanos"]
    assert tableros.POR_CLAVE["simulador"].vivo is True
