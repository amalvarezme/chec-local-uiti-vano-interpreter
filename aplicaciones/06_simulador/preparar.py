"""Congela el arranque del simulador y escribe el cuaderno delgado que lo sirve.

## El problema

El arranque del simulador DERIVA: abre el CSV de 540 MB, lee tres shapefiles de
180 MB y carga un artefacto de bolsas de 190 MB, para terminar con una tabla de vano
x ventana, un catalogo de controles y unas trazas de mapa que, juntas, son dos
ordenes de magnitud mas pequenas. Medido sobre esta base:

| | derivando | con el paquete |
|---|---|---|
| bytes leidos al arrancar | 909 MB | 94,5 MB |
| memoria residente | 2.867 MB | 579 MB |
| tiempo de carga | 7,1 s | 0,3 s |

En Databricks eso decide cuantas sesiones caben en un contenedor. En una portatil
decide otra cosa igual de concreta: si reiniciar el simulador cuesta siete segundos y
casi tres gigas, o menos de uno y medio giga.

## Una sola implementacion, sin parchear ningun cuaderno

Derivar es `chec_tableros.simulador.derivacion` y el tablero es
`chec_tableros.simulador.tablero`. Este archivo solo hace dos cosas: llama a la
derivacion y congela lo que devuelve, y escribe un cuaderno de una celda que lee ese
paquete y arma el tablero.

Antes esto se conseguia PARCHEANDO el cuaderno 06 por texto: seis marcas que tenian
que aparecer exactamente una vez, en celdas identificadas por su indice, para
convertir el camino caro en el barato y silenciar la narrativa. Funcionaba, y el
precio era que cambiar una linea del cuaderno rompiera la aplicacion en un archivo
que no la mencionaba. Ahora los dos caminos son dos funciones del mismo modulo y lo
unico que cambia entre ellos es cual se llama.

El cuaderno servido se genera entero desde aqui y vive en `cuaderno/` dentro de esta
aplicacion. Es codigo generado: no se edita a mano y no se versiona.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "_comun"))

import huellas as _huellas  # noqa: E402
import raiz as _raiz  # noqa: E402

# `src/` al path ANTES de importar la derivacion. Hasta ahora esto lo hacia la celda 1
# del cuaderno, que este archivo ejecutaba; al dejar de ejecutarla, sin esta linea el
# import de abajo falla con `ModuleNotFoundError` en un archivo que no menciona ninguna
# celda.
if str(_raiz.RAIZ_SRC) not in sys.path:
    sys.path.insert(0, str(_raiz.RAIZ_SRC))

from chec_tableros.simulador import derivacion as _derivacion  # noqa: E402

PAQUETE = AQUI / "paquete"
COPIA = AQUI / "cuaderno" / "06_simulador.ipynb"

# --- De que depende el paquete ---------------------------------------------------
# Todo lo que el paquete congela sale de aqui, y el manifiesto guarda la huella de
# cada uno para que `iniciar` pueda decir si alguno se movio. Antes solo se registraba
# el cuaderno, y editar `Variables_simular.xlsx` dejaba a la aplicacion sirviendo el
# catalogo anterior sin dar ningun error.
#
# El cuaderno 06 ya NO esta en esta lista, y su ausencia es deliberada: nada de aqui
# lo lee. Vigilar un archivo que no es insumo cuesta una reconstruccion de 7 s cada
# vez que alguien lo toca, y el dia que se borre -- fase 4 de este mismo cambio --
# seria la huella de un archivo inexistente, o sea una reconstruccion en CADA
# apertura, en silencio. El codigo que de verdad decide lo que hay dentro del paquete
# entra por `INSUMOS_ARBOL`, que cubre `src/` entero.
#
# Por CONTENIDO lo pequenio -- los cuatro archivos que viajan dentro del paquete,
# ~1 MB en total --, porque su sha1 cuesta microsegundos y un `git checkout` mueve la
# fecha de todo sin cambiar nada.
INSUMOS_POR_CONTENIDO = (
    # Este mismo archivo. No aporta nada al paquete, pero es quien ESCRIBE el cuaderno
    # que la aplicacion sirve: cambiar la celda generada de abajo no mueve ningun otro
    # insumo, asi que sin esta linea la aplicacion seguiria sirviendo el cuaderno viejo
    # y el cambio no llegaria nunca. Mismo error que se corrigio con
    # `Variables_simular.xlsx`, un nivel mas arriba.
    Path(__file__).resolve(),
    _raiz.datos("geometria_kmeans_014_v1.json"),
    _raiz.datos("models", "mil_vano_ventana_v1.pt"),
    _raiz.datos("Actividades_mantenimiento_costos_2026.xlsx"),
    _raiz.datos("Variables_simular.xlsx"),
    # No viaja dentro del paquete y se lee DOS veces, por dos caminos distintos:
    # `derivacion.derivar()` lo pasa al pipeline -- y de ahi salen las features, que si
    # se congelan --, y el tablero lo abre en cada apertura para nombrar las variables
    # del panel. La primera lectura es la que obliga a vigilarlo: editarlo dejaba a la
    # aplicacion sirviendo unas features anteriores, en silencio. El mismo error que
    # `Variables_simular.xlsx`, un archivo mas alla; ahora hay una prueba que compara
    # las dos listas para que no haya un tercero.
    #
    # La segunda lectura es la unica cosa que la aplicacion servida toma de `data/` y no
    # de su paquete. Copiarlo dentro cambiaria lo que el paquete contiene -- y con ello
    # su golden --, asi que se deja anotado y no se toca aqui.
    _raiz.datos("Variables_seleccion.xlsx"),
)
# Por MARCA lo pesado: 909 MB que hashear costaria segundos en CADA arranque, contra
# los 0,3 s que tarda el paquete en cargar. Un `git lfs pull` puede provocar una
# reconstruccion de mas; nunca una de menos.
#
# De cada shapefile se miran el `.shp` y el `.dbf`: la geometria vive en el primero y
# los atributos con los que se hace el join -- `G3E_FID`, `CIRCUITO` -- en el segundo,
# asi que mirar solo uno deja pasar la mitad de los cambios posibles.
INSUMOS_POR_MARCA = (
    _raiz.datos("Indicadores_vano_v3.csv"),
    _raiz.datos("derived", "bolsas_mil_full.joblib"),
    *(_raiz.datos("GEO", f"{_nombre}.{_ext}")
      for _nombre in ("MVLINSEC", "GDBCHEC_TRANSFOR", "SWITCHES")
      for _ext in ("shp", "dbf")),
)


# El codigo que la derivacion IMPORTA, y que decide la forma de casi todo lo que el
# paquete congela: las bolsas, la tabla vano x ventana, las trazas de mapa, el catalogo
# de controles. Eran 67 archivos sin vigilar, medidos.
#
# Aqui el hueco era mas estrecho que en los visores y por eso costaba mas verlo: el
# TABLERO se arma vivo en el kernel en cada apertura, asi que un cambio en
# `ventanas_015.py` que solo toque el dibujo si llega. El que no llegaba es el que toca
# lo CONGELADO -- `construir_ventanas`, `seleccionar_bolsas`, la geometria de 01.4 --, y
# ese se sirve viejo sin dar ningun error.
#
# Como UNA huella del arbol: las huellas se indexan por nombre de archivo y los dos
# paquetes tienen su `__init__.py`. Cuesta 1,4 ms contra los 0,3 s que tarda el paquete
# en cargar.
INSUMOS_ARBOL = (_raiz.RAIZ_REPO / "src",)


def huellas_actuales() -> dict:
    """La huella de cada insumo AHORA. La comparacion contra la guardada la hace
    `huellas.motivo_de_reconstruccion`, y la usa el arranque de la aplicacion."""
    return _huellas.huellas_de_insumos(
        por_contenido=INSUMOS_POR_CONTENIDO, por_marca=INSUMOS_POR_MARCA,
        arboles=INSUMOS_ARBOL)

# Por debajo de esto, la derivacion produjo un objeto vacio en silencio. `X_inst.npy`
# sola pesa 88 MB, asi que un paquete de 50 MB no es un paquete valido.
MINIMO_PAQUETE_MB = 50

# Nombre del kernel que la aplicacion registra en su propio entorno y que el cuaderno
# generado declara. Deliberadamente especifico: `python3` es el nombre que usa todo el
# mundo, y coincidir con el es como se termina arrancando el interprete de otro
# proyecto.
NOMBRE_KERNEL = "chec-simulador-vano"
NOMBRE_KERNEL_VISIBLE = "CHEC -- simulador de riesgo por vano"


# --------------------------------------------------------------------------------
# Parte 1: el paquete
# --------------------------------------------------------------------------------
def construir_paquete() -> dict:
    _verificar_insumos()
    PAQUETE.mkdir(parents=True, exist_ok=True)

    print("[1/3] derivando (CSV, shapefiles y cache de bolsas)")
    t0 = time.perf_counter()
    derivado = _derivacion.derivar(raiz=_raiz.RAIZ_REPO)
    print(f"      derivacion completa en {time.perf_counter() - t0:.1f} s")

    # La unica comprobacion de COHERENCIA, y va antes de congelar nada.
    #
    # Las huellas contestan "cambio algun insumo?". No contestan "siguen hablando del
    # mismo mes?". `TABLA` sale del CSV y `BAG_INDEX` del cache de bolsas del cuaderno
    # 05: actualizar el CSV sin volver a correr el 05 mueve la huella del CSV, reconstruye
    # la aplicacion, muestra los eventos nuevos y los puntua con las bolsas anteriores.
    # Las dos mitades del tablero hablan de periodos distintos y NADA falla.
    #
    # Aqui es el unico sitio donde se puede ver: es el momento en que las dos estan en la
    # mano a la vez, y corre exactamente cuando el CSV cambia. Comprobarlo en cada
    # arranque costaria cargar 199 MB de bolsas para contestar una pregunta que solo
    # cambia al reconstruir.
    #
    # Aborta y no avisa, como las otras dos guardas de este paquete (modelo != bolsas,
    # geometrias != modelo): un paquete congelado a medias es justo lo que esto impide.
    from chec_local_interpreter.ventanas_015 import desajuste_bolsas_vs_tabla

    desajuste = desajuste_bolsas_vs_tabla(derivado.bag_index, derivado.tabla)
    if desajuste:
        raise SystemExit(
            f"\n  El cache de bolsas no corresponde al CSV: {desajuste}\n\n"
            "  Vuelve a correr notebooks/05_mil_vano_ventana.ipynb, que es quien produce\n"
            "  data/derived/bolsas_mil_full.joblib a partir del CSV, y despues repite\n"
            "  esta construccion. El orden es CSV -> 05 -> 04 -> abrir las aplicaciones.\n"
        )

    print("[2/3] congelando el resultado")
    _derivacion.congelar(derivado, PAQUETE)

    for origen in (_raiz.datos("models", "mil_vano_ventana_v1.pt"),
                   _raiz.datos("Actividades_mantenimiento_costos_2026.xlsx"),
                   # Que variables se pueden simular, con que rango y con que valores
                   # posibles. La aplicacion lo lee en cada arranque -- no queda
                   # congelado en el paquete como los demas objetos --, asi que viaja
                   # como archivo y `app.py` lo apunta por entorno.
                   _raiz.datos("Variables_simular.xlsx")):
        shutil.copy2(origen, PAQUETE / origen.name)
    # La geometria KMeans viaja con su NOMBRE de origen. Se llamaba `geometrias_014.json`
    # dentro del paquete porque el parche de la celda 3 buscaba ese nombre en el
    # cuaderno; sin parche no hay nada que lo obligue, y dos nombres para el mismo
    # archivo eran una traduccion que alguien tenia que recordar.
    #
    # Hoy NADIE lo lee desde el paquete: la unica verificacion de esa geometria vive en
    # `derivacion._geometria_verificada`, que la busca en `data/` y corre al construir.
    # Viaja igual porque es lo que hace del paquete un artefacto completo -- se puede
    # comprobar contra que geometria se congelo sin volver al repositorio.
    shutil.copy2(_raiz.datos("geometria_kmeans_014_v1.json"),
                 PAQUETE / "geometria_kmeans_014_v1.json")

    _barrer_lo_que_sobra()

    manifiesto = {
        "construido_en": time.strftime("%Y-%m-%d %H:%M:%S"),
        # Reemplaza al `cuaderno_sha1` suelto de antes: son los MISMOS insumos que
        # produjeron lo que hay en `paquete/`, y con `huellas_actuales()` al arrancar
        # basta para saber si alguno se movio.
        "insumos": huellas_actuales(),
        "n_bolsas": len(derivado.bag_index.keys),
        "n_instancias": int(derivado.x_inst.shape[0]),
        "n_features": len(derivado.features_mil),
        "archivos": {},
    }
    for archivo in sorted(PAQUETE.iterdir()):
        if archivo.name != "manifiesto.json" and archivo.is_file():
            manifiesto["archivos"][archivo.name] = {"bytes": archivo.stat().st_size}
    (PAQUETE / "manifiesto.json").write_text(
        json.dumps(manifiesto, indent=1, ensure_ascii=False), encoding="utf-8")

    total_mb = sum(v["bytes"] for v in manifiesto["archivos"].values()) / 1024**2
    for nombre, meta in manifiesto["archivos"].items():
        print(f"      {nombre:<44}{meta['bytes'] / 1024**2:>8,.1f} MB")
    print(f"      {'TOTAL':<44}{total_mb:>8,.1f} MB")
    if total_mb < MINIMO_PAQUETE_MB:
        raise SystemExit(
            f"El paquete pesa {total_mb:,.1f} MB y deberia superar {MINIMO_PAQUETE_MB} MB. "
            "La derivacion produjo un objeto vacio; revisa la salida de arriba."
        )
    return manifiesto


# Lo que una construccion completa deja dentro de `paquete/`, y nada mas. Cuatro los
# escribe `derivacion.congelar` y cuatro se copian de `data/`.
CONTENIDO_DEL_PAQUETE = frozenset({
    "tabla.parquet", "X_inst.npy", "geo.json", "catalogo.joblib",
    "mil_vano_ventana_v1.pt", "Actividades_mantenimiento_costos_2026.xlsx",
    "Variables_simular.xlsx", "geometria_kmeans_014_v1.json",
    "manifiesto.json",
})


def _barrer_lo_que_sobra() -> None:
    """Borra del paquete lo que esta construccion no escribio.

    `paquete/` no se vacia entre construcciones -- `X_inst.npy` son 88 MB y se
    reescriben en su sitio --, asi que un archivo que deja de producirse se queda
    ahi para siempre. Paso al renombrar `geometrias_014.json`: la version vieja
    sobrevivio a la nueva construccion, entro en el manifiesto y quedo dentro del
    paquete como si alguien todavia la leyera.

    Es la misma clase de mentira que persiguen las huellas, del otro lado: alli el
    riesgo es servir un dato viejo, aqui es CONSERVAR uno que ya no significa nada.
    """
    for archivo in PAQUETE.iterdir():
        if archivo.is_file() and archivo.name not in CONTENIDO_DEL_PAQUETE:
            print(f"      sobra de una construccion anterior, se borra: {archivo.name}")
            archivo.unlink()


def _verificar_insumos() -> None:
    _raiz.verificar_repo()
    requeridos = {
        _raiz.datos("Indicadores_vano_v3.csv"): "la base de eventos",
        _raiz.datos("Variables_seleccion.xlsx"): "el diccionario de variables",
        _raiz.datos("Variables_simular.xlsx"): "el catalogo de variables a simular",
        _raiz.datos("Actividades_mantenimiento_costos_2026.xlsx"): "el catalogo de costos",
        _raiz.datos("GEO", "MVLINSEC.shp"): "la geometria de los vanos",
        _raiz.datos("models", "mil_vano_ventana_v1.pt"): "el modelo MIL (cuaderno 05)",
        _raiz.datos("derived", "bolsas_mil_full.joblib"): "el cache de bolsas (cuaderno 05)",
        _raiz.datos("geometria_kmeans_014_v1.json"): "la geometria KMeans, versionada",
    }
    faltan = [f"  {ruta}  --  {que}" for ruta, que in requeridos.items() if not ruta.exists()]
    if faltan:
        raise SystemExit(
            "Faltan insumos para construir el simulador:\n" + "\n".join(faltan) +
            "\n\nLos de data/derived/ y el modelo los produce "
            "05_mil_vano_ventana.ipynb; geometria_kmeans_014_v1.json esta versionado "
            "(lo produce scripts/exportar_geometria.py). "
            "El CSV puede ser un puntero de Git LFS sin descargar: `git lfs pull`."
        )
    csv = _raiz.datos("Indicadores_vano_v3.csv")
    if csv.stat().st_size < 1024 * 1024:
        raise SystemExit(f"{csv} es un puntero de Git LFS sin descargar. Corre `git lfs pull`.")


# --------------------------------------------------------------------------------
# Parte 2: el cuaderno de una celda que sirve la aplicacion
# --------------------------------------------------------------------------------
# Todo lo que la aplicacion necesita saber cabe aqui: donde quedo el paquete, donde
# vive el codigo del tablero y cual es la barra de cerrar. Antes eran seis parches de
# texto sobre un cuaderno de 5.094 lineas, cada uno exigiendo que su marca apareciera
# exactamente una vez.
#
# Las dos rutas entran por el ENTORNO y no escritas aqui dentro. Escritas serian rutas
# absolutas de la maquina que construyo, y este cuaderno sobrevive a que el repositorio
# se mueva: el paquete no se reconstruye si las huellas no se movieron, y las huellas no
# miran donde esta el repositorio. `app.py` las pone justo antes de lanzar Voila, que es
# el unico que arranca esto.
CELDA = """\
# GENERADO por preparar.py -- no se edita a mano; se reescribe en cada construccion.
import os
import sys
from pathlib import Path

PAQUETE = Path(os.environ['PAQUETE_06']).resolve()
for _ruta in (os.environ['RAIZ_SRC_06'], os.environ['APP_06']):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)

import cierre
from chec_tableros.simulador import derivacion, tablero

display(tablero.construir(
    derivacion.cargar(PAQUETE),
    costos=PAQUETE / 'Actividades_mantenimiento_costos_2026.xlsx',
    encabezado=[cierre.barra()],
))
"""


def escribir_cuaderno() -> Path:
    """Escribe el cuaderno de una celda que Voila sirve, y comprueba que compila.

    No lleva narrativa, y su ausencia es deliberada. El cuaderno 06 explicaba la
    pregunta que responde el ranking, la matematica de la busqueda del grupo Bajo y
    como leer cada panel: eso es lo que lo hacia util COMO CUADERNO y lo que sobra
    en una aplicacion, donde el usuario viene a operar el tablero. Se conserva en el
    README de esta aplicacion, que es donde alguien lo va a buscar.
    """
    codigo = CELDA.splitlines(keepends=True)
    # Compila ANTES de escribir: un error de sintaxis aqui solo aparecia al arrancar,
    # dentro del kernel de Voila, como una pagina en blanco.
    compile("".join(codigo), str(COPIA), "exec")

    documento = {
        "cells": [{"cell_type": "code", "execution_count": None, "metadata": {},
                   "outputs": [], "source": codigo}],
        "metadata": {
            # Kernel PROPIO de la aplicacion, con un nombre que no puede chocar con
            # nada. `python3` es el que usa todo el mundo, y Voila lo resuelve contra
            # los kernels instalados EN LA MAQUINA: se vio arrancando el interprete de
            # otro proyecto, ya borrado, y respondiendo 500 con un FileNotFoundError sin
            # relacion aparente. `app.py` registra este nombre dentro del entorno de la
            # aplicacion antes de arrancar.
            "kernelspec": {"display_name": NOMBRE_KERNEL_VISIBLE,
                           "language": "python", "name": NOMBRE_KERNEL},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    COPIA.parent.mkdir(parents=True, exist_ok=True)
    COPIA.write_text(json.dumps(documento, indent=1, ensure_ascii=False),
                     encoding="utf-8")
    return COPIA


