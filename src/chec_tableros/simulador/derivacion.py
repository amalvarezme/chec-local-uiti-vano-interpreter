"""El arranque caro del simulador: derivar una vez, congelar, y servir lo congelado.

## El problema que resuelve

Las siete primeras celdas del cuaderno 06 DERIVAN: abren el CSV de 566 MB, leen
tres shapefiles de 180 MB y cargan un cache de bolsas de 199 MB, para terminar con
una tabla de vano x ventana, un catalogo de controles y unas trazas de mapa que,
juntas, son dos ordenes de magnitud mas pequenas. Medido:

| | derivando | leyendo el paquete |
|---|---|---|
| bytes leidos al arrancar | 909 MB | 94,5 MB |
| memoria residente | 2.867 MB | 579 MB |
| tiempo de carga | 7,1 s | 0,3 s |

Antes eso se conseguia ejecutando las celdas del propio cuaderno con `exec()`. Ese
diseno evitaba duplicar la derivacion -- su virtud real -- al precio de que el
constructor dependiera de los INDICES de celda de un `.ipynb`, de que nadie
pudiera importar la derivacion desde otro sitio, y de que no hubiera forma de
probarla sin abrir un cuaderno.

Aqui vive ahora, una sola vez. El cuaderno la LLAMA, igual que el constructor, asi
que la propiedad que importaba -- una sola implementacion -- se conserva sin el
acoplamiento a las celdas.

## Los dos caminos

- `derivar()` es el camino caro. Lo corre quien construye el paquete y quien abre
  el cuaderno contra los datos completos.
- `cargar(paquete)` es el barato. Lo corre la aplicacion servida, que nunca ve el
  CSV ni los shapefiles.

Los dos devuelven el MISMO `Derivado`, y por eso el tablero no sabe cual corrio.

## Las guardas van aqui, no en el que llama

Tres comprobaciones abortan la derivacion: que la geometria KMeans sea la
esperada, que la del modelo MIL coincida con ella, y que las features del MIL
empiecen por las de MGCECDL. No son adorno: si el modelo se hubiera entrenado con
otra geometria, sus clases usarian los mismos cuatro colores para significar otra
cosa, y nada en pantalla lo diria. Viven aqui porque un paquete congelado a medias
es exactamente lo que impiden.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from chec_impacto.data import procesar_dataset_completo
from chec_impacto.data.bags import cargar_bolsas
from chec_impacto.models.criticality_assignment import (
    CLAVE_ESPACIO_CANONICO,
    GEOMETRIAS_SHA1_ESPERADO,
    cargar_geometria_014,
    verificar_sha1_geometrias,
)
from chec_impacto.models.mil_persistencia import cargar_modelo_mil
from chec_local_interpreter.vano_controls import build_knobs
from chec_local_interpreter.ventanas_015 import (
    RUTA_GEOMETRIA,
    construir_tabla_vano_ventana,
    construir_ventanas,
)

# La misma ventana climatica con la que se entreno (`03_mgcecdl_training`). Cambiarla
# aqui y no alla produce features que el modelo nunca vio, sin que nada falle.
VENTANA_CLIMATICA_HORAS = 12

# Cinco decimales son ~1,1 m a esta latitud: mas resolucion no se ve en el mapa y si
# se paga en bytes: son 180 MB de shapefile reducidos a unas listas de coordenadas.
DECIMALES_COORDENADA = 5


@dataclass(frozen=True)
class Derivado:
    """Lo que el arranque produce y el paquete congela.

    Son los objetos que las celdas 8-16 del cuaderno leen del arranque. Que sea un
    dataclass y no un dict suelto es deliberado: un nombre mal escrito falla al
    construirlo, no diez celdas mas abajo.
    """

    # De `procesar_dataset_completo`. `Xdata` NO viaja: solo alimentaba `build_knobs`,
    # cuyo resultado ya esta aqui como `knobs`. Exponerlo obligaria al camino barato a
    # inventar un DataFrame vacio, y `Xdf` es justo uno de los nombres que el verificador
    # de la aplicacion prohibe porque significaba "se leyo el CSV".
    feature_names: list[str]
    label_encoders: dict
    max_values_imputed: dict
    # Del cache de bolsas y del modelo MIL
    x_inst: np.ndarray
    features_mil: list[str]
    bag_index: Any
    mil: Any
    # De las ventanas deslizantes y los shapefiles
    ventanas: Any
    tabla: pd.DataFrame
    geo_por_circuito: dict
    trafos: dict
    switches: dict
    # Del catalogo de controles
    knobs: list


def derivar(
    *,
    raiz: Path | None = None,
    ventana_climatica_horas: int = VENTANA_CLIMATICA_HORAS,
    clave_espacio: str = CLAVE_ESPACIO_CANONICO,
) -> Derivado:
    """El camino caro: CSV, shapefiles y cache de bolsas.

    `raiz` existe para las pruebas y para que el cuaderno pueda pasar la suya; por
    defecto se deduce de la ubicacion de este archivo, que es lo unico estable
    cuando el llamante puede ser un cuaderno con cualquier directorio de trabajo.
    """
    raiz = _raiz_del_repo() if raiz is None else Path(raiz)
    datos_dir = raiz / "data"

    geometria = _geometria_verificada(clave_espacio)

    # --- El dataset completo, sin muestreo -------------------------------------
    # `use_sampling=False` y `filtro_uiti_max=None` no son configuracion: dejan
    # `context_df` alineado FILA A FILA con la matriz de features, que es lo que
    # permite reusar la misma mascara (circuito, ventana) para el mapa historico y
    # para las predicciones del modelo sobre esas mismas filas.
    datos = procesar_dataset_completo(
        path_clima=datos_dir / "Indicadores_vano_v3.csv",
        path_variables_seleccion=datos_dir / "Variables_seleccion.xlsx",
        use_sampling=False,
        min_samples_per_codigo=5,
        target="UITI_VANO",
        filtro_uiti_max=None,
        ventana_climatica_horas=ventana_climatica_horas,
    )
    feature_names = list(datos["features"])
    n_filas_x = len(datos["X"])
    # Sin `.copy()`: `reset_index` ya devuelve un objeto propio y `df_original_copy`
    # es -- como dice su nombre -- una copia que el pipeline hizo. Copiar otra vez
    # dejaba dos juegos vivos: medido, 506 MB duplicados.
    xdf = datos["Xdata"].reset_index(drop=True)
    context_df = datos["df_original_copy"].reset_index(drop=True)
    label_encoders = datos.get("label_encoders", {})
    max_values_imputed = datos.get("max_values_imputed", {})
    if len(context_df) != n_filas_x:
        raise ValueError(
            "context_df y la matriz de features quedaron desalineados "
            f"({len(context_df)} vs {n_filas_x}): la mascara compartida entre el "
            "mapa historico y el modelo dejaria de senalar las mismas filas."
        )
    del datos

    # --- Bolsas y modelo -------------------------------------------------------
    bolsas = cargar_bolsas(datos_dir / "derived" / "bolsas_mil_full.joblib")
    # `float32` y no el `float64` del artefacto: los pesos del modelo son float32,
    # asi que la conversion ya ocurria en cada llamada y la mitad de cada numero se
    # descartaba. Medido: la clase simulada y el UITI salen identicos bit a bit, y
    # la matriz baja de 184,7 a 92,4 MB.
    x_inst = np.asarray(bolsas["X"], dtype=np.float32)
    features_mil, bag_index = bolsas["features"], bolsas["bag_index"]
    del bolsas

    # `device='cpu'` a proposito: una seleccion son decenas de instancias, asi que
    # el traslado a GPU/MPS cuesta mas de lo que ahorra.
    mil = cargar_modelo_mil(
        datos_dir / "models" / "mil_vano_ventana_v1.pt",
        device="cpu",
        features_esperadas=features_mil,
    )
    _verificar_modelo_contra_geometria(mil, geometria)
    if list(features_mil[: len(feature_names)]) != list(feature_names):
        raise ValueError(
            "Las features del MIL ya no empiezan por las de MGCECDL: el catalogo "
            "de knobs apuntaria a columnas equivocadas."
        )

    # --- Ventanas, tabla y geometria fisica ------------------------------------
    ventanas = construir_ventanas(context_df["FECHA"])
    tabla = construir_tabla_vano_ventana(context_df, ventanas)
    circuitos = set(tabla["CIRCUITO"].astype(str).unique())

    geo_dir = datos_dir / "GEO"
    geo_por_circuito = _geometria_de_vanos(geo_dir / "MVLINSEC.shp", circuitos)
    trafos = _equipo(geo_dir / "GDBCHEC_TRANSFOR.shp", circuitos)
    switches = _equipo(geo_dir / "SWITCHES.shp", circuitos)

    knobs = build_knobs(
        feature_names=feature_names,
        original_feature_df=xdf,
        label_encoders=label_encoders,
        max_values_imputed=max_values_imputed,
    )

    return Derivado(
        feature_names=feature_names, label_encoders=label_encoders,
        max_values_imputed=max_values_imputed, x_inst=x_inst,
        features_mil=features_mil, bag_index=bag_index, mil=mil,
        ventanas=ventanas, tabla=tabla, geo_por_circuito=geo_por_circuito,
        trafos=trafos, switches=switches, knobs=knobs,
    )


def congelar(derivado: Derivado, destino: Path) -> None:
    """Escribe los cuatro archivos que la derivacion produce.

    Los otros cuatro del paquete son copias literales de archivos de `data/`, y
    copiarlos es del constructor, no de aqui: este modulo solo responde por lo que
    deriva.
    """
    import joblib

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    derivado.tabla.to_parquet(destino / "tabla.parquet", compression="zstd")
    # Contiguo y float32: es lo que se puede mapear en memoria al arrancar.
    np.save(destino / "X_inst.npy",
            np.ascontiguousarray(derivado.x_inst, dtype=np.float32))
    (destino / "geo.json").write_text(
        json.dumps({"geo": derivado.geo_por_circuito, "trafos": derivado.trafos,
                    "switches": derivado.switches}, separators=(",", ":")),
        encoding="utf-8",
    )
    joblib.dump(
        {"knobs": derivado.knobs, "feature_names": derivado.feature_names,
         "label_encoders": derivado.label_encoders,
         "max_values_imputed": derivado.max_values_imputed,
         "bag_index": derivado.bag_index,
         "features_mil": list(derivado.features_mil),
         "ventanas": derivado.ventanas},
        destino / "catalogo.joblib",
        compress=3,
    )


def cargar(paquete: Path) -> Derivado:
    """El camino barato: lo que la aplicacion servida corre en cada arranque.

    No abre el CSV, ni los shapefiles, ni el cache de bolsas. Devuelve el MISMO
    `Derivado` que `derivar()`, y por eso el tablero no sabe cual de los dos corrio.
    """
    import joblib

    paquete = Path(paquete)
    catalogo = joblib.load(paquete / "catalogo.joblib")
    geo = json.loads((paquete / "geo.json").read_text("utf-8"))

    return Derivado(
        feature_names=catalogo["feature_names"],
        label_encoders=catalogo["label_encoders"],
        max_values_imputed=catalogo["max_values_imputed"],
        # `mmap_mode='r'`: 88 MB que el sistema pagina bajo demanda en vez de
        # copiarlos al arrancar. Es la mitad de por que el paquete carga en 0,3 s.
        x_inst=np.load(paquete / "X_inst.npy", mmap_mode="r"),
        features_mil=catalogo["features_mil"],
        bag_index=catalogo["bag_index"],
        mil=cargar_modelo_mil(paquete / "mil_vano_ventana_v1.pt", device="cpu",
                              features_esperadas=catalogo["features_mil"]),
        ventanas=catalogo["ventanas"],
        tabla=pd.read_parquet(paquete / "tabla.parquet"),
        geo_por_circuito=geo["geo"], trafos=geo["trafos"], switches=geo["switches"],
        knobs=catalogo["knobs"],
    )


# --------------------------------------------------------------------------------
# Interno
# --------------------------------------------------------------------------------
def _raiz_del_repo() -> Path:
    return Path(__file__).resolve().parents[3]


def _geometria_verificada(clave_espacio: str):
    """Falla RAPIDO, antes de abrir 566 MB de CSV.

    Si la geometria se movio, no tiene sentido esperar el procesamiento pesado
    para enterarse.
    """
    sha1_real, coincide = verificar_sha1_geometrias(
        RUTA_GEOMETRIA, esperado=GEOMETRIAS_SHA1_ESPERADO)
    if not coincide:
        raise ValueError(
            f"La geometria KMeans no coincide con la esperada "
            f"(esperado={GEOMETRIAS_SHA1_ESPERADO}, real={sha1_real}). "
            "El simulador depende de esa geometria."
        )
    return cargar_geometria_014(RUTA_GEOMETRIA, clave_espacio)


def _verificar_modelo_contra_geometria(mil, geometria) -> None:
    """La guarda que hace comparables los dos mapas del tablero.

    Si el MIL se hubiera entrenado con OTRA geometria KMeans, sus clases usarian
    los mismos cuatro colores para significar otra cosa.
    """
    for campo in ("offset", "scale", "centroides"):
        if not np.allclose(getattr(mil.geometria, campo), getattr(geometria, campo)):
            raise ValueError(
                f"La geometria del modelo MIL difiere de la versionada en {campo}: "
                "sus clases NO son las del mapa base y no pueden compartir paleta."
            )
    if tuple(mil.geometria.logs) != tuple(geometria.logs):
        raise ValueError("El modelo MIL usa otros ejes logaritmicos que la geometria.")


def _norm_id(serie: pd.Series) -> pd.Series:
    return (serie.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
            .replace({"": pd.NA, "<NA>": pd.NA, "nan": pd.NA, "None": pd.NA}))


def _geometria_de_vanos(ruta: Path, circuitos: set[str]) -> dict:
    """Las trazas de cada vano, por circuito, ya reducidas a listas de coordenadas.

    Solo lectura y reindexado geoespacial: la logica que valdria la pena probar por
    separado ya vive en `TABLA` y en `capas_mapa_historico`.
    """
    import geopandas as gpd

    lineas = gpd.read_file(ruta)
    if str(lineas.crs) != "EPSG:4326":
        lineas = lineas.to_crs("EPSG:4326")
    lineas["FID_VANO_GEO"] = _norm_id(lineas["G3E_FID"])
    utiles = lineas[lineas["CIRCUITO"].astype(str).isin(circuitos)]

    por_circuito: dict = {}
    for circuito, grupo in utiles.groupby(utiles["CIRCUITO"].astype(str)):
        fids, lats, lons = [], [], []
        for fid, geom in zip(grupo["FID_VANO_GEO"], grupo.geometry):
            if geom is None or geom.is_empty:
                continue
            partes = ([geom] if geom.geom_type == "LineString"
                      else list(getattr(geom, "geoms", [])))
            for parte in partes:
                xs, ys = parte.xy
                fids.append(str(fid))
                lats.append([round(v, DECIMALES_COORDENADA) for v in ys])
                lons.append([round(v, DECIMALES_COORDENADA) for v in xs])
        if fids:
            # `bounds` es lo que permite encuadrar el mapa sobre el circuito
            # elegido: [lat_min, lat_max, lon_min, lon_max].
            todas_lat = [v for l in lats for v in l]
            todas_lon = [v for l in lons for v in l]
            por_circuito[circuito] = {
                "fids": fids, "lat": lats, "lon": lons,
                "bounds": [round(min(todas_lat), DECIMALES_COORDENADA),
                           round(max(todas_lat), DECIMALES_COORDENADA),
                           round(min(todas_lon), DECIMALES_COORDENADA),
                           round(max(todas_lon), DECIMALES_COORDENADA)],
            }
    return por_circuito


def _equipo(ruta: Path, circuitos: set[str]) -> dict:
    """Transformadores o interruptores del circuito.

    Si el shapefile no esta, el mapa se dibuja sin equipos en vez de fallar: son
    contexto de lectura, no el dato del tablero.
    """
    if not ruta.exists():
        return {}

    import geopandas as gpd

    g = gpd.read_file(ruta)
    if str(g.crs) != "EPSG:4326":
        g = g.to_crs("EPSG:4326")
    g = g[g["CIRCUITO"].astype(str).isin(circuitos)]
    g = g[g.geometry.notna() & ~g.geometry.is_empty]
    return {
        c: {"lat": [round(float(p.y), DECIMALES_COORDENADA) for p in gg.geometry],
            "lon": [round(float(p.x), DECIMALES_COORDENADA) for p in gg.geometry]}
        for c, gg in g.groupby(g["CIRCUITO"].astype(str))
    }
