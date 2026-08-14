"""Congela el arranque del cuaderno 06 y deja una copia que lee ese resultado.

## El problema

El cuaderno 06 dedica sus primeras siete celdas a DERIVAR cosas: abre el CSV de
540 MB, lee tres shapefiles de 180 MB y carga un artefacto de bolsas de 190 MB, para
terminar con una tabla de vano x ventana, un catalogo de controles y unas trazas de
mapa que, juntas, son dos ordenes de magnitud mas pequenas. Medido sobre esta base:

| | cuaderno tal cual | con el paquete |
|---|---|---|
| bytes leidos al arrancar | 909 MB | 94,5 MB |
| memoria residente | 2.867 MB | 579 MB |
| tiempo de carga | 7,1 s | 0,3 s |

En Databricks eso decide cuantas sesiones caben en un contenedor. En una portatil
decide otra cosa igual de concreta: si reiniciar el simulador cuesta siete segundos y
casi tres gigas, o menos de uno y medio giga.

## La forma de hacerlo sin duplicar el cuaderno

El constructor **ejecuta las celdas del propio cuaderno** y congela el resultado. No
reimplementa la derivacion: si el cuaderno cambia como agrega o como clasifica, el
paquete cambia con el en la siguiente construccion.

La copia que sirve la aplicacion se genera aplicando parches acotados sobre el
cuaderno original -- nunca a mano --, y cada parche exige que su marca aparezca
exactamente una vez. Un parche que no encuentra su sitio detiene la construccion en
vez de producir un cuaderno que muere dentro del servidor sin dejar rastro util.

`06_uiti_vano_explicabilidad_simulador.ipynb` NO se modifica. La copia vive en
`cuaderno/` dentro de esta aplicacion.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "_comun"))

import cuaderno as _cuaderno  # noqa: E402
import huellas as _huellas  # noqa: E402
import raiz as _raiz  # noqa: E402

CUADERNO = _raiz.CUADERNOS_APPS / "06_uiti_vano_explicabilidad_simulador.ipynb"
PAQUETE = AQUI / "paquete"
COPIA = AQUI / "cuaderno" / "06_simulador.ipynb"

# Las celdas que solo derivan. De la 8 en adelante empieza el tablero, que la copia
# conserva intacto.
CELDAS_DE_ARRANQUE = range(0, 8)

# --- De que depende el paquete ---------------------------------------------------
# Todo lo que el paquete congela sale de aqui, y el manifiesto guarda la huella de
# cada uno para que `iniciar` pueda decir si alguno se movio. Antes solo se registraba
# el cuaderno, y editar `Variables_simular.xlsx` dejaba a la aplicacion sirviendo el
# catalogo anterior sin dar ningun error.
#
# Por CONTENIDO lo pequenio -- el cuaderno y los cuatro archivos que viajan dentro del
# paquete, ~1 MB en total --, porque su sha1 cuesta microsegundos y un `git checkout`
# mueve la fecha de todo sin cambiar nada.
INSUMOS_POR_CONTENIDO = (
    CUADERNO,
    # Este mismo archivo. No aporta nada al paquete, pero es quien ESCRIBE la copia
    # parcheada del cuaderno: cambiar un bloque inyectado aqui -- el silenciador, la
    # barra de cierre -- no mueve ningun otro insumo, asi que sin esta linea la
    # aplicacion seguiria sirviendo la copia vieja y el cambio no llegaria nunca.
    # Mismo error que se corrigio con `Variables_simular.xlsx`, un nivel mas arriba.
    Path(__file__).resolve(),
    _raiz.datos("derived", "geometrias_014.json"),
    _raiz.datos("models", "mil_vano_ventana_v1.pt"),
    _raiz.datos("Actividades_mantenimiento_costos_2026.xlsx"),
    _raiz.datos("Variables_simular.xlsx"),
    # No viaja dentro del paquete, pero la celda 4 -- que si se congela -- lo lee para
    # nombrar las variables. Se exigia para construir y no se vigilaba: editarlo dejaba
    # a la aplicacion sirviendo los nombres anteriores, en silencio. El mismo error que
    # `Variables_simular.xlsx`, un archivo mas alla; ahora hay una prueba que compara
    # las dos listas para que no haya un tercero.
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


# El codigo que las celdas de arranque IMPORTAN, y que decide la forma de casi todo lo
# que el paquete congela: las bolsas, la tabla vano x ventana, las trazas de mapa, el
# catalogo de controles. Eran 67 archivos sin vigilar, medidos.
#
# Aqui el hueco era mas estrecho que en los visores y por eso costaba mas verlo: las
# celdas del TABLERO (11 a 16) corren vivas en el kernel en cada apertura, asi que un
# cambio en `ventanas_015.py` que solo toque el dibujo si llega. El que no llegaba es el
# que toca lo CONGELADO -- `construir_ventanas`, `seleccionar_bolsas`, la geometria de
# 01.4 --, y ese se sirve viejo sin dar ningun error.
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

# Por debajo de esto, alguna celda produjo un objeto vacio en silencio. `X_inst.npy`
# sola pesa 88 MB, asi que un paquete de 50 MB no es un paquete valido.
MINIMO_PAQUETE_MB = 50

# Nombre del kernel que la aplicacion registra en su propio entorno y que la copia del
# cuaderno declara. Deliberadamente especifico: `python3` es el nombre que usa todo el
# mundo, y coincidir con el es como se termina arrancando el interprete de otro
# proyecto.
NOMBRE_KERNEL = "chec-simulador-vano"
NOMBRE_KERNEL_VISIBLE = "CHEC -- simulador de riesgo por vano"


# --------------------------------------------------------------------------------
# Parte 1: el paquete
# --------------------------------------------------------------------------------
def construir_paquete() -> dict:
    import joblib
    import numpy as np

    _verificar_insumos()
    PAQUETE.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] ejecutando las celdas de arranque de {CUADERNO.name}")
    t0 = time.perf_counter()
    espacio = _cuaderno.ejecutar(CUADERNO, celdas=CELDAS_DE_ARRANQUE)
    print(f"      arranque completo en {time.perf_counter() - t0:.1f} s")

    print("[2/3] congelando el resultado")
    espacio["TABLA"].to_parquet(PAQUETE / "tabla.parquet", compression="zstd")

    # `ascontiguousarray` + float32: es el dtype con el que el modelo opera de todos
    # modos, y un .npy contiguo es lo que se puede mapear en memoria en el arranque.
    np.save(PAQUETE / "X_inst.npy",
            np.ascontiguousarray(espacio["X_INST"], dtype=np.float32))

    (PAQUETE / "geo.json").write_text(
        json.dumps({"geo": espacio["GEO_POR_CIRCUITO"],
                    "trafos": espacio["TRAFOS"],
                    "switches": espacio["SWITCHES"]}, separators=(",", ":")),
        encoding="utf-8",
    )

    joblib.dump(
        {"knobs": espacio["KNOBS"],
         "feature_names": espacio["feature_names"],
         "label_encoders": espacio["label_encoders"],
         "max_values_imputed": espacio["max_values_imputed"],
         "bag_index": espacio["BAG_INDEX"],
         "features_mil": list(espacio["FEATURES_MIL"]),
         "ventanas": espacio["VENTANAS"]},
        PAQUETE / "catalogo.joblib",
        compress=3,
    )

    for origen in (_raiz.datos("derived", "geometrias_014.json"),
                   _raiz.datos("models", "mil_vano_ventana_v1.pt"),
                   _raiz.datos("Actividades_mantenimiento_costos_2026.xlsx"),
                   # Que variables se pueden simular, con que rango y con que valores
                   # posibles. La aplicacion lo lee en cada arranque -- no queda
                   # congelado en el paquete como los demas objetos --, asi que viaja
                   # como archivo y `app.py` lo apunta por entorno.
                   _raiz.datos("Variables_simular.xlsx")):
        shutil.copy2(origen, PAQUETE / origen.name)

    manifiesto = {
        "construido_en": time.strftime("%Y-%m-%d %H:%M:%S"),
        # Reemplaza al `cuaderno_sha1` suelto de antes: son los MISMOS insumos que
        # produjeron lo que hay en `paquete/`, y con `huellas_actuales()` al arrancar
        # basta para saber si alguno se movio.
        "insumos": huellas_actuales(),
        "n_bolsas": len(espacio["BAG_INDEX"].keys),
        "n_instancias": int(espacio["X_INST"].shape[0]),
        "n_features": len(espacio["FEATURES_MIL"]),
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
            "Alguna celda produjo un objeto vacio; revisa la salida de arriba."
        )
    return manifiesto


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
        _raiz.datos("derived", "geometrias_014.json"): "la geometria KMeans (cuaderno 04)",
    }
    faltan = [f"  {ruta}  --  {que}" for ruta, que in requeridos.items() if not ruta.exists()]
    if faltan:
        raise SystemExit(
            "Faltan insumos para construir el simulador:\n" + "\n".join(faltan) +
            "\n\nLos dos de data/derived/ y el modelo los produce "
            "05_mil_vano_ventana.ipynb; geometrias_014.json sale de 04. "
            "El CSV puede ser un puntero de Git LFS sin descargar: `git lfs pull`."
        )
    csv = _raiz.datos("Indicadores_vano_v3.csv")
    if csv.stat().st_size < 1024 * 1024:
        raise SystemExit(f"{csv} es un puntero de Git LFS sin descargar. Corre `git lfs pull`.")


# --------------------------------------------------------------------------------
# Parte 2: la copia del cuaderno que lee el paquete
# --------------------------------------------------------------------------------
def _reemplazar(fuente: str, viejo: str, nuevo: str, *, etiqueta: str) -> str:
    apariciones = fuente.count(viejo)
    if apariciones != 1:
        raise SystemExit(
            f"[{etiqueta}] el texto a reemplazar aparece {apariciones} veces y deberia "
            f"aparecer 1. El cuaderno 06 cambio en esa zona y esta aplicacion tiene que "
            f"actualizarse.\n  buscaba: {viejo.strip().splitlines()[0][:90]!r}"
        )
    return fuente.replace(viejo, nuevo, 1)


def _reemplazar_rango(fuente: str, desde: str, hasta: str, nuevo: str, *, etiqueta: str) -> str:
    """Reemplaza desde la marca `desde` hasta el final de la marca `hasta`, inclusive.

    Se trabaja con marcas y no con el bloque literal completo para que un comentario
    reformateado en medio del bloque no rompa la construccion. Las dos marcas se
    exigen unicas, que es lo que impide reemplazar el trozo equivocado.
    """
    for marca in (desde, hasta):
        if fuente.count(marca) != 1:
            raise SystemExit(
                f"[{etiqueta}] la marca {marca.strip()[:70]!r} aparece "
                f"{fuente.count(marca)} veces y deberia aparecer 1."
            )
    i = fuente.index(desde)
    j = fuente.index(hasta, i) + len(hasta)
    return fuente[:i] + nuevo + fuente[j:]


_CARGA_CATALOGO = """_cat = joblib.load(PAQUETE / 'catalogo.joblib')
feature_names = list(_cat['feature_names'])
label_encoders = _cat['label_encoders']
max_values_imputed = _cat['max_values_imputed']
# `context_df`, `Xdf` y `n_filas_x` NO se definen, y eso es el objetivo del cambio:
# eran los 1.919 MB que costaba `procesar_dataset_completo`, y ninguna celda de la 9
# en adelante los vuelve a nombrar.
print(f'{len(feature_names)} features (del paquete; la aplicacion no abre el CSV)')"""

_CARGA_INSTANCIAS = """assert RUTA_MODELO_MIL.exists(), (
    f'Falta {RUTA_MODELO_MIL.name} en el paquete. Vuelve a construir la aplicacion.')

# `mmap_mode='r'` y no una carga normal: los 88 MB de la matriz de instancias se
# quedan en el cache de paginas del sistema operativo, no en la memoria privada del
# proceso. Leer unos miles de filas de ahi cuesta 0 MB adicionales, y si algun dia
# corren dos sesiones a la vez comparten una sola copia en vez de llevar 88 MB cada
# una. Depende de que `mil_simulador_015` indexe ANTES de promover a float64
# (`np.asarray(X_inst[filas], ...)`, no `np.asarray(X_inst, ...)[filas]`): la forma
# vieja leia los 88 MB enteros del disco en cada clic y convertia el mapeo en copia.
X_INST = np.load(PAQUETE / 'X_inst.npy', mmap_mode='r')
FEATURES_MIL = list(_cat['features_mil'])
BAG_INDEX = _cat['bag_index']"""

# --- Silenciar la salida de las celdas en la aplicacion ---------------------------
# El camino obvio para esto es marcar las celdas y pasarle a Voila
# `--TagRemovePreprocessor.remove_all_outputs_tags`. NO FUNCIONA, y se comprobo: ese
# preprocesador borra las salidas que el cuaderno YA TRAE GUARDADAS, y las de la
# aplicacion se generan en vivo al ejecutarse. Con la marca puesta y el flag pasado, la
# pagina seguia abriendo con "Geometria 01.4 verificada...", "70 features..." y
# "MIL cargado...".
#
# Asi que se silencia en el origen: `print` y `display` se sustituyen por funciones que
# no hacen nada, y la unica llamada que SI tiene que mostrar algo -- la del tablero --
# se reescribe para usar la referencia real, guardada antes de sustituirlas. Es
# determinista y no depende de que ningun preprocesador se comporte de una manera.
#
# Es seguro porque el cuaderno no usa `widgets.Output`: se verifico que ningun `print`
# alimenta un area de salida de la interfaz. Si algun dia se agrega uno, esto lo
# silenciaria y habria que exceptuarlo.
_SILENCIO = '''
# --- Solo en la aplicacion: el tablero es lo unico que se muestra -------------------
# Las celdas de abajo informan de lo que van cargando, y eso es util en el cuaderno y
# ruido en la aplicacion. Se guarda la referencia real de `display` porque la celda del
# tablero la necesita para mostrarse.
_display_real = display


def print(*_a, **_k):  # noqa: A001 -- sombrea el print del cuaderno a proposito
    pass


def display(*_a, **_k):  # noqa: A001
    pass

'''

# --- Boton de cerrar, solo en la aplicacion --------------------------------------
# Entra dentro del propio tablero y no como una celda aparte: asi Voila lo pinta
# siempre junto a la figura, sin depender de en que orden queden las celdas.
_BOTON_CERRAR = '''
# --- Boton de cerrar (solo en la aplicacion, no en el cuaderno) ---------------------
# Cerrar es TRES cosas y hay que hacerlas en este orden: cerrar la pestania, apagar el
# servidor y, con el, los kernels que cuelgan de el. El orden importa porque el segundo
# paso mata al proceso que le esta hablando al navegador: si se apaga primero, el
# mensaje que cierra la pestania nunca sale del kernel.
_CERRAR_AVISO = widgets.HTML('')
# `Output` y no un `HTML`: el JavaScript de un `HTML` no se ejecuta -- ipywidgets lo
# mete por `innerHTML`, y el navegador no corre los `<script>` que llegan asi.
_CERRAR_SALIDA = widgets.Output()

# `window.close()` no siempre esta permitido: Chrome lo acepta cuando la pestania no
# tiene historial propio -- que es el caso de la que abre `iniciar.command`, MEDIDO --,
# pero lo rechaza si el usuario navego dentro de ella, y Firefox lo rechaza por defecto.
# Por eso hay respaldo: si a los 400 ms la pestania sigue viva, se queda con el aviso de
# cerrado a pantalla completa en vez de con el tablero muerto, que es lo que se veria si
# esto se diera por hecho.
_JS_CERRAR = """
window.close();
setTimeout(function () {
  if (window.closed) { return; }
  document.body.innerHTML =
    "<div style='font:17px/1.7 system-ui;padding:80px 40px;color:#2b2b2b'>" +
    "<b style='font-size:22px'>Simulador cerrado</b><br>" +
    "El servidor se detuvo. Ya puedes cerrar esta pestana.<br>" +
    "<span style='color:#666'>Para volver a abrirlo: Iniciar.app (macOS) o " +
    "iniciar.bat (Windows).</span></div>";
}, 400);
"""


import os as _os_cierre

# La pone CriticidadCHEC en el entorno cuando es el quien lanza el simulador. Vacia
# cuando alguien arranca la aplicacion por su cuenta, y entonces la barra es la de
# siempre: no hay menu al que volver.
_MENU_CRITICIDAD = _os_cierre.environ.get('MENU_CRITICIDAD', '')

# Volver al menu: se cierra la pestania igual que arriba, pero si no se puede se NAVEGA
# al menu en vez de dejar un aviso de despedida. Deja al usuario donde pidio ir.
_JS_VOLVER = """
window.close();
setTimeout(function () {
  if (window.closed) { return; }
  window.location = "__MENU__";
}, 400);
""".replace('__MENU__', _MENU_CRITICIDAD)



def _cerrar_aplicacion(_boton, _js=None):
    import os
    import signal
    import threading

    from IPython.display import Javascript

    ruta = os.environ.get('ARCHIVO_PID_06')
    # El pid se lee del archivo que escribio `app.py`, NUNCA de `os.getppid()`: el
    # padre de un kernel es una suposicion sobre como jupyter_client lo lanzo, y
    # mandar SIGTERM a un pid supuesto puede matar un proceso que no es la aplicacion.
    if not ruta or not os.path.exists(ruta):
        _CERRAR_AVISO.value = (
            "<p style='color:#c62828;font:14px system-ui'>No se encontro el proceso de "
            "la aplicacion. Cierrala desde la terminal con Ctrl+C.</p>")
        return
    with open(ruta, encoding='utf-8') as f:
        pid = int(f.read().strip())
    for _b in _BOTONES_CIERRE:
        _b.disabled = True
    _CERRAR_AVISO.value = (
        "<div style='font:16px/1.6 system-ui;padding:8px;color:#2b2b2b'>"
        "<b>Cerrando el simulador...</b></div>")
    with _CERRAR_SALIDA:
        _display_real(Javascript(_js or _JS_CERRAR))
    # El SIGTERM va con retraso y en otro hilo. SIGTERM a Voila se lleva por delante a
    # ESTE kernel -- comprobado: apaga los siete que llegaron a estar vivos a la vez --,
    # asi que matarlo aqui mismo cortaria el mensaje de arriba antes de que salga por el
    # socket y la pestania se quedaria abierta sobre un tablero sin servidor.
    threading.Timer(0.8, os.kill, (pid, signal.SIGTERM)).start()


_BOTONES_CIERRE = []

if _MENU_CRITICIDAD:
    # Lanzado desde el menu: las dos acciones que ofrece la barra de los otros cuatro
    # tableros. Las dos apagan SOLO este simulador -- el mismo SIGTERM al pid que dejo
    # escrito `app.py`, que se lleva Voila y sus kernels -- y se diferencian en donde
    # dejan al usuario. Apagar las cinco aplicaciones es cosa del "Cerrar todo" del menu
    # y de nadie mas: desde aqui se cerraba tambien lo que el usuario no estaba mirando.
    _BOTON_VOLVER = widgets.Button(
        description='Volver al menu',
        tooltip='Apaga el simulador y vuelve a CriticidadCHEC',
        layout=widgets.Layout(width='170px'))
    _BOTON_VOLVER.on_click(lambda b: _cerrar_aplicacion(b, _JS_VOLVER))
    _BOTON_CERRAR_APP = widgets.Button(
        description='Cerrar', button_style='danger',
        tooltip='Apaga el simulador y cierra esta pestania',
        layout=widgets.Layout(width='130px'))
    _BOTON_CERRAR_APP.on_click(_cerrar_aplicacion)
    _BOTONES_CIERRE = [_BOTON_VOLVER, _BOTON_CERRAR_APP]
else:
    _BOTON_CERRAR_APP = widgets.Button(
        description='Cerrar', button_style='danger',
        tooltip='Cierra esta pestania y apaga el servidor de la aplicacion',
        layout=widgets.Layout(width='130px'))
    _BOTON_CERRAR_APP.on_click(_cerrar_aplicacion)
    _BOTONES_CIERRE = [_BOTON_CERRAR_APP]

_BARRA_CERRAR = widgets.HBox(
    [*_BOTONES_CIERRE, _CERRAR_AVISO, _CERRAR_SALIDA],
    layout=widgets.Layout(width='100%', justify_content='flex-end', padding='4px 12px'))

'''

_CARGA_GEO = """# Trazas de mapa del paquete. En el cuaderno esto son tres `gpd.read_file` sobre
# 180 MB de shapefiles que se reducen a estas listas de coordenadas redondeadas a
# cinco decimales; la aplicacion no vuelve a hacer esa reduccion ni importa geopandas.
_geo = json.loads((PAQUETE / 'geo.json').read_text('utf-8'))
GEO_POR_CIRCUITO, TRAFOS, SWITCHES = _geo['geo'], _geo['trafos'], _geo['switches']"""


def preparar_copia() -> Path:
    documento = json.loads(CUADERNO.read_text("utf-8"))
    celdas = documento["cells"]

    def parchear(indice: int, funcion) -> None:
        fuente = "".join(celdas[indice]["source"])
        celdas[indice]["source"] = funcion(fuente).splitlines(keepends=True)

    # --- celda 1: imports y raiz del paquete -------------------------------------
    def celda1(f: str) -> str:
        f = _reemplazar(f, "import asyncio\nimport gc\nimport os\n",
                        "import asyncio\nimport gc\nimport joblib\nimport json\nimport os\n",
                        etiqueta="1: json y joblib")
        # geopandas sale porque la aplicacion no abre ningun shapefile; el import de
        # `procesar_dataset_completo` sale porque dejar a mano la funcion que lee el
        # CSV de 540 MB es como se reintroduce el costo que este paquete quita.
        f = _reemplazar(f, "import geopandas as gpd\n", "", etiqueta="1: geopandas")
        f = _reemplazar(f, "from chec_impacto.data import procesar_dataset_completo\n", "",
                        etiqueta="1: pipeline")
        f = _reemplazar(f, "from chec_impacto.data.bags import cargar_bolsas\n", "",
                        etiqueta="1: bolsas")
        return _reemplazar(
            f,
            "for _path_a_agregar in (ROOT, ROOT / 'src'):\n"
            "    if str(_path_a_agregar) not in sys.path:\n"
            "        sys.path.insert(0, str(_path_a_agregar))\n",
            "for _path_a_agregar in (ROOT, ROOT / 'src'):\n"
            "    if str(_path_a_agregar) not in sys.path:\n"
            "        sys.path.insert(0, str(_path_a_agregar))\n"
            "\n"
            "# Todo lo que el cuaderno derivaba al arrancar viene ya resuelto de aqui.\n"
            "PAQUETE = Path(os.environ['PAQUETE_06']).resolve()\n"
            + _SILENCIO,
            etiqueta="1: PAQUETE",
        )

    # --- celda 3: geometria KMeans desde el paquete -------------------------------
    def celda3(f: str) -> str:
        return _reemplazar_rango(
            f,
            "GEOMETRIAS_PATH = DEFAULT_OUTPUT_PATH",
            "    extraer_geometrias_014(DEFAULT_NOTEBOOK_PATH, GEOMETRIAS_PATH)",
            "GEOMETRIAS_PATH = PAQUETE / 'geometrias_014.json'",
            etiqueta="3: geometria",
        )

    # --- celda 4: catalogo en vez del pipeline ------------------------------------
    def celda4(f: str) -> str:
        f = _reemplazar(
            f, "COSTOS_ITEMS_PATH = ROOT / 'data' / 'Actividades_mantenimiento_costos_2026.xlsx'",
            "COSTOS_ITEMS_PATH = PAQUETE / 'Actividades_mantenimiento_costos_2026.xlsx'",
            etiqueta="4: costos")
        f = _reemplazar(f, "MODEL_DIR = ROOT / 'data' / 'models'", "MODEL_DIR = PAQUETE",
                        etiqueta="4: modelo")
        # El rango empieza en el COMENTARIO y no en la llamada: ese parrafo explica
        # por que el pipeline corre sin muestreo para dejar `context_df` alineado
        # fila a fila, y en la copia ya no hay ni pipeline ni `context_df`. Dejarlo
        # seria documentacion que describe un paso que no ocurre.
        return _reemplazar_rango(
            f,
            "# Mismo preprocesamiento real usado en entrenamiento",
            "print(f'{len(context_df):,} filas | {len(feature_names)} features')",
            _CARGA_CATALOGO,
            etiqueta="4: pipeline",
        )

    # --- celda 5: matriz de instancias mapeada en memoria -------------------------
    def celda5(f: str) -> str:
        return _reemplazar_rango(
            f,
            "RUTA_BOLSAS_MIL = ROOT / 'data' / 'derived' / 'bolsas_mil_full.joblib'",
            "del BOLSAS\ngc.collect()",
            _CARGA_INSTANCIAS,
            etiqueta="5: bolsas",
        )

    # --- celda 6: tabla y trazas del paquete --------------------------------------
    def celda6(f: str) -> str:
        f = _reemplazar_rango(
            f,
            "VENTANAS = construir_ventanas(context_df['FECHA'])",
            "TABLA = construir_tabla_vano_ventana(context_df, VENTANAS)",
            "VENTANAS = _cat['ventanas']\nTABLA = pd.read_parquet(PAQUETE / 'tabla.parquet')",
            etiqueta="6: tabla",
        )
        f = _reemplazar_rango(
            f,
            "def _norm_id(serie):",
            "SWITCHES = _equipo('SWITCHES.shp')",
            _CARGA_GEO,
            etiqueta="6: shapefiles",
        )
        return _reemplazar(f, "del _lineas, _utiles\ngc.collect()", "gc.collect()",
                           etiqueta="6: liberacion")

    # --- celda 7: catalogo de controles -------------------------------------------
    def celda7(f: str) -> str:
        return _reemplazar_rango(
            f,
            "KNOBS = build_knobs(",
            "max_values_imputed=max_values_imputed,\n)",
            # `build_knobs` necesita `Xdf`, que es justo el DataFrame que el parche de
            # la celda 4 dejo de construir.
            "KNOBS = _cat['knobs']",
            etiqueta="7: knobs",
        )

    # --- celda 16: boton de cerrar dentro del tablero ------------------------------
    def celda16(f: str) -> str:
        return _reemplazar(
            f,
            "APP = widgets.VBox([ESTILO, PANEL, ENCUADRES, fig], "
            "layout=widgets.Layout(width='100%'))",
            _BOTON_CERRAR
            + "APP = widgets.VBox([_BARRA_CERRAR, ESTILO, PANEL, ENCUADRES, fig], "
              "layout=widgets.Layout(width='100%'))",
            etiqueta="16: boton de cerrar",
        )

    def celda16_mostrar(f: str) -> str:
        # La unica salida que la aplicacion SI muestra.
        return _reemplazar(f, "display(APP)", "_display_real(APP)",
                           etiqueta="16: mostrar el tablero")

    for indice, funcion in ((1, celda1), (3, celda3), (4, celda4),
                            (5, celda5), (6, celda6), (7, celda7), (16, celda16),
                            (16, celda16_mostrar)):
        parchear(indice, funcion)

    # --- La aplicacion muestra el TABLERO, nada mas --------------------------------
    # El cuaderno explica: la pregunta que responde el ranking, la matematica de la
    # busqueda del grupo Bajo, como leer cada panel. Eso es lo que lo hace util como
    # cuaderno y es justo lo que sobra en una aplicacion, donde el usuario viene a
    # operar el tablero y no a leer su derivacion. En el cuaderno del repositorio todo
    # eso se conserva intacto; aqui se retira de dos formas:
    #
    #  1. Las celdas de texto se eliminan.
    #  2. La salida de las celdas de codigo -- los `print` de la carga, la tabla de
    #     variables, el catalogo de costos -- se silencia en el origen (ver _SILENCIO).
    #     La entrada ya la esconde Voila por su cuenta.
    #
    # Se hace DESPUES de parchear, porque los parches indexan por la numeracion
    # original del cuaderno y eliminar celdas la corre.
    celdas[:] = [c for c in celdas if c["cell_type"] != "markdown"]

    mostrar = [c for c in celdas if "_display_real(APP)" in "".join(c["source"])]
    if len(mostrar) != 1:
        raise SystemExit(
            f"Se esperaba exactamente una celda que muestre el tablero, y hay "
            f"{len(mostrar)}. El cuaderno 06 cambio."
        )

    # Salidas fuera: la copia del repositorio pesa 261 KB, y una ejecutada local
    # reincrusta megabytes de imagenes y de estado de widgets.
    for celda in celdas:
        if celda["cell_type"] == "code":
            celda["outputs"] = []
            celda["execution_count"] = None

    # Kernel PROPIO de la aplicacion, con un nombre que no puede chocar con nada.
    # El cuaderno declara `python3`, y Voila resuelve ese nombre contra los kernels
    # instalados EN LA MAQUINA: si el entorno de la aplicacion no registra el suyo,
    # Voila toma cualquier otro -- se vio arrancando el interprete de otro proyecto,
    # ya borrado, y respondiendo 500 con un FileNotFoundError sin relacion aparente.
    # `app.py` registra este nombre dentro del entorno antes de arrancar.
    documento["metadata"]["kernelspec"] = {
        "display_name": NOMBRE_KERNEL_VISIBLE,
        "language": "python",
        "name": NOMBRE_KERNEL,
    }

    _verificar_copia(celdas)

    COPIA.parent.mkdir(parents=True, exist_ok=True)
    COPIA.write_text(json.dumps(documento, indent=1, ensure_ascii=False), encoding="utf-8")
    return COPIA


def _sin_comentarios(codigo: str) -> str:
    """Devuelve el codigo sin comentarios ni literales de texto.

    La comprobacion de abajo busca nombres prohibidos, y tiene que mirar lo que se
    EJECUTA. Los parches dejan comentarios que explican por que esos objetos ya no
    existen -- y esa explicacion es justo lo que hay que conservar --, asi que
    compararlos como si fueran codigo convertiria la documentacion en un fallo.
    """
    import io
    import tokenize

    piezas = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(codigo).readline):
            if token.type not in (tokenize.COMMENT, tokenize.STRING):
                piezas.append(token.string)
    except tokenize.TokenError:
        # Una celda que no tokeniza ya fallo en `compile`; aqui no se opina.
        return codigo
    return " ".join(piezas)


def _verificar_copia(celdas: list) -> None:
    """Comprueba que la copia compila y que no quedo ninguna referencia al camino caro."""
    codigo_efectivo = ""
    for indice, celda in enumerate(celdas):
        if celda["cell_type"] != "code":
            continue
        codigo = "".join(celda["source"])
        try:
            compile(codigo, f"copia:celda{indice}", "exec")
        except SyntaxError as exc:
            raise SystemExit(
                f"El parche dejo la celda {indice} sin compilar: {exc}. "
                "Es un error de esta aplicacion, no del cuaderno."
            ) from exc
        codigo_efectivo += _sin_comentarios(codigo) + "\n"

    # `compile` no detecta un nombre usado y nunca definido, que es exactamente el
    # fallo que dejaria un parche incompleto. Estos cuatro son los caminos caros que
    # los parches eliminan, asi que su ausencia es la prueba de que no quedo nada
    # colgando: `context_df` y `Xdf` son los 1.919 MB del pipeline, y `gpd` los
    # 326 MB de los shapefiles.
    for prohibido in ("context_df", "Xdf", "procesar_dataset_completo", "gpd"):
        if prohibido in codigo_efectivo:
            raise SystemExit(
                f"La copia del cuaderno todavia EJECUTA {prohibido!r}. El parche quedo "
                "incompleto y la aplicacion volveria a leer el CSV o los shapefiles."
            )
