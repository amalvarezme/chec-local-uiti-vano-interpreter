"""Invocacion canonica de la skill /clima. Envuelve clima_engine con las rutas del proyecto
y el flujo de gates. Cada funcion es un paso; la skill decide cual llamar segun el modo.

Orden por modo: elegir fuente -> Gate 1 ubicaciones -> Gate 2 API -> Gate 3 limites -> procesar.
El resultado va a data/; lo operativo (rate log, cache HTTP) a .clima_cache/.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from chec_local_interpreter import clima_engine as ce

V3_NOMBRE = "Indicadores_vano_v3.csv"


def _raiz() -> Path:
    cwd = Path.cwd().resolve()
    for cand in [cwd, *cwd.parents]:
        if (cand / "src" / "chec_impacto").exists():
            return cand
    return cwd


def rutas() -> tuple[Path, Path]:
    raiz = _raiz()
    cache = raiz / ".clima_cache"
    cache.mkdir(parents=True, exist_ok=True)
    return raiz / "data", cache


def listar_tablas() -> list[str]:
    data_dir, _ = rutas()
    return sorted(p.name for p in data_dir.glob("*.csv"))


def _cliente():
    _, cache = rutas()
    return ce.crear_cliente(cache)


# --- Gate 1: deteccion de columnas de posicion + validacion ---
def detectar_posicion(archivo: str) -> dict:
    """Busca las columnas de lon/lat en la tabla elegida. Si 'encontrado' es False, la skill
    debe PREGUNTAR al usuario cuales son (y pasarlas luego a las funciones de Modo B)."""
    return ce.detectar_columnas_posicion(_leer_fuente(archivo))


# --- Gate 2: configuracion de API ---
def config_gratuita() -> ce.ConfigAPI:
    return ce.ConfigAPI(modo="gratuita")


def config_paga(apikey: str, cap_mes: int | None = None) -> ce.ConfigAPI:
    """La apikey la escribe el usuario (interactiva). cap_mes por defecto = Professional (5M)."""
    return ce.ConfigAPI(modo="paga", apikey=apikey, cap_mes=cap_mes)


def presupuesto_disponible(config: ce.ConfigAPI) -> int:
    _, cache = rutas()
    return ce.crear_limitador(cache, config).disponible()


# --- Modo A (fuente fija v3, coordenadas X1/Y1 del evento) ---
def a_gate1() -> dict:
    data_dir, _ = rutas()
    df = pd.read_csv(data_dir / V3_NOMBRE, usecols=lambda c: c in set(ce.COORD_V3))
    return ce.validar_ubicaciones(df, *ce.COORD_V3)


def a_gate3_necesarios() -> int:
    data_dir, _ = rutas()
    return ce.contar_pendientes_v3(data_dir / V3_NOMBRE)


def a_ejecutar(config: ce.ConfigAPI, limite_filas: int | None = None) -> dict:
    data_dir, cache = rutas()
    return ce.actualizar_v3(data_dir / V3_NOMBRE, cache, datetime.now(timezone.utc), config,
                            _cliente(), limite_filas=limite_filas)


# --- Modo B (tabla elegida; col_lon/col_lat detectadas o indicadas por el usuario) ---
def _leer_fuente(archivo: str) -> pd.DataFrame:
    data_dir, _ = rutas()
    return pd.read_csv(data_dir / archivo, sep="|", dtype={"G3E_FID": "string", "CIRCUITO": "string"})


def _cols_pos(archivo: str, col_lon: str | None, col_lat: str | None) -> tuple[str, str]:
    if col_lon and col_lat:
        return col_lon, col_lat
    det = ce.detectar_columnas_posicion(_leer_fuente(archivo))
    if not det["encontrado"]:
        raise ValueError(f"No se detectaron columnas de posicion en {archivo}; indica col_lon/col_lat. "
                         f"Columnas disponibles: {det['columnas']}")
    return det["lon"], det["lat"]


def b_gate1(archivo: str, col_lon: str | None = None, col_lat: str | None = None) -> dict:
    """Gate 1: detecta (o usa las indicadas) columnas de posicion y valida un minimo de coords."""
    df = _leer_fuente(archivo)
    if not (col_lon and col_lat):
        det = ce.detectar_columnas_posicion(df)
        if not det["encontrado"]:
            return {"ok": False, "necesita_preguntar": True, "columnas": det["columnas"],
                    "mensaje": "No detecte columnas de posicion; indica cuales son (lon, lat)."}
        col_lon, col_lat = det["lon"], det["lat"]
    return ce.validar_ubicaciones(df, col_lon, col_lat)


def b_gate3_necesarios(archivo: str, modo: str, fecha_inicio: str, fecha_fin: str,
                       col_lon: str | None = None, col_lat: str | None = None) -> int:
    data_dir, _ = rutas()
    col_lon, col_lat = _cols_pos(archivo, col_lon, col_lat)
    fuente = _leer_fuente(archivo)
    _, _, columnas = ce.layout_clima_b(modo, fecha_inicio, fecha_fin)
    ruta_prev = data_dir / ce.nombre_salida(archivo, fecha_inicio, fecha_fin)
    if ruta_prev.exists():
        prev = pd.read_csv(ruta_prev, sep="|")
        for c in [c for c in columnas if c not in prev.columns]:
            prev[c] = float("nan")
        return ce.coords_pendientes_b(prev, columnas, col_lon, col_lat)
    return int(fuente[[col_lon, col_lat]].drop_duplicates().shape[0])


def b_calcular(archivo: str, modo: str, fecha_inicio: str, fecha_fin: str, config: ce.ConfigAPI,
               col_lon: str | None = None, col_lat: str | None = None,
               limite_coords: int | None = None, resume: bool = True) -> pd.DataFrame:
    """Procesamiento del Modo B (aun sin guardar). Reanuda una salida previa del mismo origen
    si existe y resume=True. col_lon/col_lat: detectadas o indicadas por el usuario."""
    data_dir, cache = rutas()
    col_lon, col_lat = _cols_pos(archivo, col_lon, col_lat)
    fuente = _leer_fuente(archivo)
    limitador = ce.crear_limitador(cache, config)
    base_previa = None
    ruta_prev = data_dir / ce.nombre_salida(archivo, fecha_inicio, fecha_fin)
    if resume and ruta_prev.exists():
        base_previa = pd.read_csv(ruta_prev, sep="|", dtype={"G3E_FID": "string", "CIRCUITO": "string"})
    return ce.consultar_puntos(fuente, archivo, modo, fecha_inicio, fecha_fin, limitador,
                               datetime.now(timezone.utc), config, _cliente(),
                               col_lon=col_lon, col_lat=col_lat,
                               limite_coords=limite_coords, base_previa=base_previa)


def b_previas(resultado: pd.DataFrame) -> list[Path]:
    data_dir, _ = rutas()
    return ce.buscar_salidas_previas(data_dir, str(resultado["origen_id"].iloc[0]))


def b_guardar(resultado: pd.DataFrame, archivo: str) -> Path:
    data_dir, _ = rutas()
    ini, fin = str(resultado["rango_inicio"].iloc[0]), str(resultado["rango_fin"].iloc[0])
    return ce.guardar_resultado(resultado, data_dir / ce.nombre_salida(archivo, ini, fin))


def b_unificar_y_guardar(resultado: pd.DataFrame, ruta_previa: Path, archivo: str) -> Path:
    data_dir, _ = rutas()
    unido = ce.unificar_por_horas(pd.read_csv(ruta_previa, sep="|"), resultado)
    ini, fin = str(unido["rango_inicio"].iloc[0]), str(unido["rango_fin"].iloc[0])
    return ce.guardar_resultado(unido, data_dir / ce.nombre_salida(archivo, ini, fin))


def concatenar(nombres: list[str]) -> pd.DataFrame:
    data_dir, _ = rutas()
    return ce.concatenar_salidas([data_dir / n for n in nombres])
