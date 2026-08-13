"""RED/GREEN tests para `aplicaciones/_comun/huellas.py`.

El paquete del simulador (aplicacion del cuaderno 06) congela el resultado de las
celdas de arranque: la tabla vano x ventana, la matriz de instancias, las trazas de
mapa y el catalogo de controles. Todo eso sale de unos INSUMOS -- el cuaderno, el
CSV de eventos, el artefacto de bolsas, los shapefiles y cuatro archivos que se
copian tal cual --, y el resto del cuaderno consume esos objetos suponiendo su forma.

Un insumo editado con un paquete viejo es la unica manera de que el tablero dibuje
datos que ya no corresponden **sin que nada de error**. Ya paso: al ajustar
`data/Variables_simular.xlsx` la aplicacion siguio sirviendo el catalogo anterior,
porque el manifiesto solo guardaba el sha1 del cuaderno.

Este modulo produce la huella de cada insumo y compara la guardada contra la actual.
Es de biblioteca estandar y sin estado, asi que se prueba sin construir nada.

Dos formas de huella, y la diferencia es deliberada:

  - **por contenido** (sha1) para lo pequenio: el cuaderno y los cuatro archivos que
    viajan dentro del paquete suman ~1 MB, y su sha1 cuesta microsegundos;
  - **por marca** (bytes + mtime) para lo pesado: el CSV, las bolsas y los shapefiles
    suman 909 MB, y hashearlos en CADA arranque costaria segundos contra los 0,3 s
    que tarda el paquete en cargar. Una marca falla del lado seguro: un `git lfs pull`
    puede provocar una reconstruccion de mas, nunca una de menos.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

MODULO = (
    Path(__file__).resolve().parents[1]
    / "aplicaciones" / "_comun" / "huellas.py"
)


@pytest.fixture(scope="module")
def huellas():
    """El modulo, cargado por ruta: vive fuera del paquete instalable a proposito
    -- las aplicaciones arrancan con el Python del sistema, antes de que exista
    ningun entorno --, asi que no se puede importar por nombre."""
    spec = importlib.util.spec_from_file_location("huellas_aplicaciones", MODULO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _archivo(tmp_path: Path, nombre: str, contenido: bytes = b"x") -> Path:
    ruta = tmp_path / nombre
    ruta.write_bytes(contenido)
    return ruta


# --- La huella de un archivo ----------------------------------------------------------
def test_la_huella_por_contenido_es_el_sha1(huellas, tmp_path):
    """Lo pequenio se compara por lo que DICE, no por cuando se toco: un `git
    checkout` mueve la fecha de todos los archivos sin cambiar ninguno, y con marcas
    de tiempo eso reconstruiria el paquete entero sin motivo."""
    ruta = _archivo(tmp_path, "Variables_simular.xlsx", b"hoja ajustada")

    huella = huellas.huella_de_archivo(ruta, por_contenido=True)

    assert huella == {"bytes": 13, "sha1": hashlib.sha1(b"hoja ajustada").hexdigest()}


def test_la_huella_por_marca_no_lee_el_archivo(huellas, tmp_path):
    """El CSV pesa 540 MB y esto corre en cada arranque. La marca son dos datos del
    `stat`, asi que cuesta lo mismo con 540 MB que con 13 bytes."""
    ruta = _archivo(tmp_path, "Indicadores_vano_v3.csv", b"grande")

    huella = huellas.huella_de_archivo(ruta, por_contenido=False)

    assert set(huella) == {"bytes", "mtime_ns"}
    assert huella["bytes"] == 6
    assert huella["mtime_ns"] == ruta.stat().st_mtime_ns


def test_un_insumo_que_falta_se_dice_en_vez_de_lanzar(huellas, tmp_path):
    """Un insumo ausente no puede tumbar la comprobacion: es justo el caso en que hay
    que reconstruir -- y el constructor tiene su propia verificacion, que explica cual
    cuaderno lo produce."""
    huella = huellas.huella_de_archivo(tmp_path / "no_esta.csv", por_contenido=True)

    assert huella == {"falta": True}


# --- El conjunto de huellas -----------------------------------------------------------
def test_las_huellas_se_indexan_por_el_nombre_del_archivo(huellas, tmp_path):
    ruta_a = _archivo(tmp_path, "cuaderno.ipynb", b"a")
    ruta_b = _archivo(tmp_path, "Indicadores_vano_v3.csv", b"bb")

    calculadas = huellas.huellas_de_insumos(
        por_contenido=[ruta_a], por_marca=[ruta_b])

    assert set(calculadas) == {"cuaderno.ipynb", "Indicadores_vano_v3.csv"}
    assert "sha1" in calculadas["cuaderno.ipynb"]
    assert "mtime_ns" in calculadas["Indicadores_vano_v3.csv"]


# --- La comparacion, que es lo que decide si se reconstruye ---------------------------
def test_sin_cambios_no_hay_motivo_para_reconstruir(huellas):
    guardadas = {"a.ipynb": {"bytes": 1, "sha1": "aa"}}

    assert huellas.motivo_de_reconstruccion(guardadas, dict(guardadas)) is None


def test_el_motivo_nombra_el_insumo_que_cambio(huellas):
    """Un "hay que reconstruir" sin decir por que obliga a adivinar cual de los ocho
    insumos se movio."""
    guardadas = {"a.ipynb": {"bytes": 1, "sha1": "aa"},
                 "b.xlsx": {"bytes": 2, "sha1": "bb"}}
    actuales = {"a.ipynb": {"bytes": 1, "sha1": "aa"},
                "b.xlsx": {"bytes": 3, "sha1": "cc"}}

    motivo = huellas.motivo_de_reconstruccion(guardadas, actuales)

    assert motivo is not None and "b.xlsx" in motivo and "a.ipynb" not in motivo


def test_varios_cambios_se_nombran_todos(huellas):
    guardadas = {"a.ipynb": {"sha1": "aa"}, "b.xlsx": {"sha1": "bb"}}
    actuales = {"a.ipynb": {"sha1": "zz"}, "b.xlsx": {"sha1": "yy"}}

    motivo = huellas.motivo_de_reconstruccion(guardadas, actuales)

    assert "a.ipynb" in motivo and "b.xlsx" in motivo


def test_un_insumo_nuevo_en_la_lista_obliga_a_reconstruir(huellas):
    """El paquete se construyo sin ese insumo, asi que lo que congelo no lo tuvo en
    cuenta."""
    motivo = huellas.motivo_de_reconstruccion({}, {"nuevo.xlsx": {"sha1": "aa"}})

    assert motivo is not None and "nuevo.xlsx" in motivo


def test_un_manifiesto_sin_huellas_obliga_a_reconstruir(huellas):
    """Es el paquete construido por la version anterior, que solo guardaba el sha1 del
    cuaderno. No se puede afirmar que sus insumos siguen siendo estos, asi que se
    reconstruye y se dice que es por el formato, no por un cambio."""
    motivo = huellas.motivo_de_reconstruccion(None, {"a.ipynb": {"sha1": "aa"}})

    assert motivo is not None and "anterior" in motivo.lower()


def test_un_insumo_que_dejo_de_estar_tambien_es_un_motivo(huellas):
    """Si el archivo desaparecio, lo que el paquete congelo ya no se puede reproducir
    y quien construya se lo va a encontrar de frente."""
    motivo = huellas.motivo_de_reconstruccion(
        {"a.csv": {"bytes": 1, "sha1": "aa"}}, {"a.csv": {"falta": True}})

    assert motivo is not None and "a.csv" in motivo
