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

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "_comun"))

import cuaderno as _cuaderno  # noqa: E402
import raiz as _raiz  # noqa: E402

CUADERNO = _raiz.CUADERNOS / "06_uiti_vano_explicabilidad_simulador.ipynb"
PAQUETE = AQUI / "paquete"
COPIA = AQUI / "cuaderno" / "06_simulador.ipynb"

# Las celdas que solo derivan. De la 8 en adelante empieza el tablero, que la copia
# conserva intacto.
CELDAS_DE_ARRANQUE = range(0, 8)

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
                   _raiz.datos("Actividades_mantenimiento_costos_2026.xlsx")):
        shutil.copy2(origen, PAQUETE / origen.name)

    manifiesto = {
        "construido_en": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cuaderno_sha1": hashlib.sha1(CUADERNO.read_bytes()).hexdigest(),
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
            "PAQUETE = Path(os.environ['PAQUETE_06']).resolve()\n",
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

    for indice, funcion in ((1, celda1), (3, celda3), (4, celda4),
                            (5, celda5), (6, celda6), (7, celda7)):
        parchear(indice, funcion)

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
