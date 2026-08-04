"""Motor de clima reutilizable para la skill ``/clima``.

Cubre el mismo funcionamiento de los dos cuadernos de clima en una sola pieza, con
pre-vuelo de 3 gates (ubicaciones -> API -> limites) y luego el modo:

- Modo A — :func:`actualizar_v3`: completa el clima por evento (25 rezagos, t..t-24)
  de las filas nuevas de ``Indicadores_vano_v3.csv``, depura y reescribe v3 de forma
  transaccional. Sin filas nuevas, pasa derecho. Soporta bloque maximo (deja pendientes).
- Modo B — :func:`consultar_puntos`: para una tabla de puntos, agrega a cada fila
  tantas columnas como (horas x variables) para un ``dia`` o un ``rango``. Formato ancho.
  Resumible: puede continuar una salida previa del mismo ``origen_id`` dejando pendientes.

Gates:
- :func:`detectar_columnas_posicion` + :func:`validar_ubicaciones` (Gate 1): detecta las
  columnas de coordenada (x1/y1, x2/y2, lon/lat, longitud/latitud...) o pide indicarlas,
  y exige un minimo de coordenadas validas.
- :class:`ConfigAPI` (Gate 2): gratuita vs paga (apikey + endpoints ``customer-``).
- :class:`LimitadorPersistente` (Gate 3): limites por ventana (gratuita) o presupuesto
  mensual (paga), con bloque maximo.

Fuente: Open-Meteo via ``openmeteo_requests`` (formato binario, precision completa, igual
que el cuaderno 01_climate). Todas las consultas se hacen en UTC y se mapean a la hora pedida.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

# Endpoints gratuitos (por defecto). El modo pago usa el prefijo ``customer-``.
FORECAST_URL_FREE = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL_FREE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL_PAID = "https://customer-api.open-meteo.com/v1/forecast"
ARCHIVE_URL_PAID = "https://customer-archive-api.open-meteo.com/v1/archive"

BOGOTA_TZ_NAME = "America/Bogota"
ARCHIVE_DELAY_DAYS = 5
MAX_RETRIES = 4
FECHA_FORMAT = "%Y-%m-%d %H:%M:%S"
RETENCION_DIAS = 32  # el log guarda 32 dias para cubrir ventana diaria y mes calendario

# Coordenadas por defecto de cada modo (lon, lat).
COORD_V3 = ("X1", "Y1")        # ubicacion del evento en v3
COORD_RED = ("XPOS1_RED_BASE", "YPOS1_RED_AFECTA")  # tabla de red

# Patrones para detectar columnas de posicion (en minusculas, en orden de preferencia).
PATRONES_LON = ["x1", "xpos1_red_base", "lon", "longitud", "longitude", "coord_x", "x", "x2", "xpos2_red_afecta"]
PATRONES_LAT = ["y1", "ypos1_red_afecta", "lat", "latitud", "latitude", "coord_y", "y", "y2", "ypos2_red_afecta"]

# Las 9 familias de clima y su nombre en Open-Meteo.
VAR_MAP = {
    "prep": "precipitation",
    "pres": "pressure_msl",
    "sp": "surface_pressure",
    "rh": "relative_humidity_2m",
    "solar_rad": "shortwave_radiation",
    "temp": "temperature_2m",
    "wind_gust_spd": "wind_gusts_10m",
    "wind_spd": "wind_speed_10m",
    "clouds": "cloud_cover",
}
API_VARIABLES = list(VAR_MAP.values())
LAGS = 25  # Modo A: t, t-1, ..., t-24

# Columnas de negocio de la depuracion final de v3 (Modo A), identicas al cuaderno.
NUMERIC_ZERO_FILL = ["PROMEDIO_KWH_VANO", "PROMEDIO_KWH_TRF", "NR_T", "CNT_USUS", "CAPACIDAD_NOMINAL"]
TEXT_ZERO_FILL = ["CALIBRE_NEUTRO"]
FECHA_TRF_COL = "FECHA_OPERACION_TRF"
FECHA_VANO_COL = "FECHA_OPERACION_VANO"
ALTURA_COL = "ALTURA"


# ---------------------------------------------------------------------------
# Gate 1 — detectar columnas de posicion
# ---------------------------------------------------------------------------
def detectar_columnas_posicion(df: pd.DataFrame) -> dict[str, Any]:
    """Busca las columnas de longitud/latitud por nombre (x1/y1, x2/y2, lon/lat,
    longitud/latitud...). Si no las encuentra, ``encontrado`` es False y la skill pregunta."""
    cols = {c.lower(): c for c in df.columns}
    lon = next((cols[p] for p in PATRONES_LON if p in cols), None)
    lat = next((cols[p] for p in PATRONES_LAT if p in cols), None)
    return {"lon": lon, "lat": lat, "encontrado": lon is not None and lat is not None,
            "columnas": list(df.columns)}


def validar_ubicaciones(df: pd.DataFrame, col_lon: str, col_lat: str, minimo: int = 1) -> dict[str, Any]:
    """Exige un minimo de coordenadas validas antes de cualquier otra cosa (Gate 1)."""
    faltan = [c for c in (col_lon, col_lat) if c not in df.columns]
    if faltan:
        return {"ok": False, "validas": 0, "invalidas": len(df),
                "mensaje": f"Faltan columnas de coordenada: {faltan}."}
    lon = pd.to_numeric(df[col_lon], errors="coerce")
    lat = pd.to_numeric(df[col_lat], errors="coerce")
    validas = int((lon.between(-180, 180) & lat.between(-90, 90)).sum())
    invalidas = int(len(df) - validas)
    ok = validas >= minimo
    return {"ok": ok, "validas": validas, "invalidas": invalidas, "lon": col_lon, "lat": col_lat,
            "mensaje": (f"{validas} coordenadas validas, {invalidas} invalidas."
                        if ok else f"Sin ubicaciones validas (minimo {minimo}). No se puede continuar.")}


# ---------------------------------------------------------------------------
# Gate 2 — configuracion de API (gratuita vs paga)
# ---------------------------------------------------------------------------
@dataclass
class ConfigAPI:
    """Elige API gratuita o paga y sus limites. En modo paga la apikey la escribe el
    usuario (interactiva); no se persiste. El historico comercial requiere plan Professional."""

    modo: str = "gratuita"          # "gratuita" | "paga"
    apikey: str | None = None
    cap_min: int = 550              # margenes bajo 600/5000/10000 de la gratuita
    cap_hora: int = 4_800
    cap_dia: int = 9_500
    cap_mes: int | None = None      # solo paga: presupuesto mensual (p.ej. 5_000_000 Professional)

    def __post_init__(self) -> None:
        if self.modo not in {"gratuita", "paga"}:
            raise ValueError("modo debe ser 'gratuita' o 'paga'.")
        if self.modo == "paga":
            if not self.apikey:
                raise ValueError("El modo 'paga' requiere que el usuario escriba la apikey.")
            if self.cap_mes is None:
                self.cap_mes = 5_000_000  # Professional por defecto (desbloquea historico)

    @property
    def forecast_url(self) -> str:
        return FORECAST_URL_PAID if self.modo == "paga" else FORECAST_URL_FREE

    @property
    def archive_url(self) -> str:
        return ARCHIVE_URL_PAID if self.modo == "paga" else ARCHIVE_URL_FREE

    def params_extra(self) -> dict[str, str]:
        return {"apikey": self.apikey} if self.modo == "paga" and self.apikey else {}


# ---------------------------------------------------------------------------
# Gate 3 — limitador de tasa persistente (ventana en gratuita, mensual en paga)
# ---------------------------------------------------------------------------
class PresupuestoDiarioAgotado(RuntimeError):
    pass


class PresupuestoMensualAgotado(RuntimeError):
    pass


class LimitadorPersistente:
    """Contabiliza ubicaciones consultadas y espera cuando haria falta. En gratuita usa
    ventanas minuto/hora/dia; en paga verifica el presupuesto mensual. Persiste en disco."""

    def __init__(self, log_path: Path, config: ConfigAPI):
        self.log_path = Path(log_path)
        self.config = config
        self.events: deque[tuple[float, int]] = deque()
        if self.log_path.exists():
            corte = time.time() - RETENCION_DIAS * 86_400
            for linea in self.log_path.read_text().splitlines():
                try:
                    item = json.loads(linea)
                    ts, peso = float(item["timestamp"]), int(item["weight"])
                    if ts >= corte:
                        self.events.append((ts, peso))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue

    def _podar(self, ahora: float) -> None:
        corte = ahora - RETENCION_DIAS * 86_400
        while self.events and self.events[0][0] < corte:
            self.events.popleft()

    def _peso_desde(self, ahora: float, segundos: int) -> int:
        return sum(p for ts, p in self.events if ts >= ahora - segundos)

    def usado_mes(self) -> int:
        ahora = datetime.now(timezone.utc)
        inicio = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        return sum(p for ts, p in self.events if ts >= inicio)

    def disponible(self) -> int:
        """Presupuesto restante para el Gate 3: diario (gratuita) o mensual (paga)."""
        ahora = time.time()
        self._podar(ahora)
        if self.config.cap_mes is not None:
            return max(0, self.config.cap_mes - self.usado_mes())
        return max(0, self.config.cap_dia - self._peso_desde(ahora, 86_400))

    def esperar(self, peso: int) -> None:
        if self.config.cap_mes is not None:  # paga: presupuesto mensual, sin espera por ventana
            if self.usado_mes() + peso > self.config.cap_mes:
                raise PresupuestoMensualAgotado(
                    f"Presupuesto mensual agotado: {self.usado_mes()} de {self.config.cap_mes}."
                )
            return
        ventanas = [(60, self.config.cap_min, "minuto"),
                    (3_600, self.config.cap_hora, "hora"),
                    (86_400, self.config.cap_dia, "dia")]
        while True:
            ahora = time.time()
            self._podar(ahora)
            esperas = []
            for segundos, capacidad, etiqueta in ventanas:
                usado = self._peso_desde(ahora, segundos)
                if usado + peso <= capacidad:
                    continue
                if segundos == 86_400:
                    raise PresupuestoDiarioAgotado(
                        f"Presupuesto seguro diario agotado: {usado} ubicaciones en 24 h."
                    )
                relevantes = [(ts, w) for ts, w in self.events if ts >= ahora - segundos]
                faltante, liberado, hasta = usado + peso - capacidad, 0, ahora
                for ts, w in relevantes:
                    liberado += w
                    hasta = ts + segundos + 2
                    if liberado >= faltante:
                        break
                esperas.append((max(1.0, hasta - ahora), etiqueta))
            if not esperas:
                return
            segundos_dormir, etiqueta = max(esperas, key=lambda x: x[0])
            print(f"Limite seguro por {etiqueta}: esperando {segundos_dormir / 60:.1f} min...")
            time.sleep(segundos_dormir)

    def registrar(self, peso: int) -> None:
        ts = time.time()
        self.events.append((ts, peso))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": ts, "weight": peso}) + "\n")


def crear_limitador(cache_dir: Path, config: ConfigAPI) -> LimitadorPersistente:
    return LimitadorPersistente(Path(cache_dir) / "open_meteo_rate_log.jsonl", config)


def crear_cliente(cache_dir: Path) -> openmeteo_requests.Client:
    """Cliente Open-Meteo con cache HTTP local + reintentos (igual que el cuaderno)."""
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    session = requests_cache.CachedSession(str(Path(cache_dir) / ".openmeteo_http_cache"), expire_after=3600)
    session = retry(session, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=session)


# ---------------------------------------------------------------------------
# Consulta horaria a Open-Meteo para UNA coordenada (siempre en UTC, precision completa)
# ---------------------------------------------------------------------------
def _serie_desde_respuesta(resp: Any) -> dict[str, Any]:
    hourly = resp.Hourly()
    tiempos = pd.date_range(
        start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
        end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=hourly.Interval()),
        inclusive="left",
    )
    out: dict[str, Any] = {"time": [t.strftime("%Y-%m-%dT%H:00") for t in tiempos]}
    for i, api_var in enumerate(API_VARIABLES):
        out[api_var] = [float(x) for x in hourly.Variables(i).ValuesAsNumpy()]
    return out


def _combinar(series_list: list[dict[str, Any]]) -> dict[str, Any]:
    por_tiempo: dict[str, dict[str, Any]] = {}
    for serie in series_list:
        for i, ts in enumerate(serie["time"]):
            fila = por_tiempo.setdefault(ts, {})
            for api_var in API_VARIABLES:
                vals = serie.get(api_var, [])
                if i < len(vals) and vals[i] is not None and not (isinstance(vals[i], float) and np.isnan(vals[i])):
                    fila[api_var] = vals[i]
    tiempos = sorted(por_tiempo)
    combinado: dict[str, Any] = {"time": tiempos}
    for api_var in API_VARIABLES:
        combinado[api_var] = [por_tiempo[ts].get(api_var) for ts in tiempos]
    return combinado


def traer_horario(lat: float, lon: float, fecha_inicio: str, fecha_fin: str,
                  limitador: LimitadorPersistente, hoy_utc: datetime, config: ConfigAPI,
                  cliente: Any) -> dict[str, Any]:
    """Serie horaria UTC [fecha_inicio, fecha_fin] (fechas ISO) para una coordenada, ruteando
    archive/forecast por antiguedad y combinando si cruza el limite. Etiquetas de tiempo en UTC."""
    inicio = datetime.fromisoformat(fecha_inicio).date()
    fin = datetime.fromisoformat(fecha_fin).date()
    frontera = (hoy_utc - timedelta(days=ARCHIVE_DELAY_DAYS)).date()
    base = {"latitude": lat, "longitude": lon, "hourly": API_VARIABLES, "timezone": "UTC", **config.params_extra()}

    peticiones: list[tuple[str, dict[str, Any]]] = []
    if fin <= frontera:
        peticiones.append((config.archive_url, {**base, "start_date": inicio.isoformat(), "end_date": fin.isoformat()}))
    elif inicio > frontera:
        dias = max(1, (hoy_utc.date() - inicio).days + 1)
        peticiones.append((config.forecast_url, {**base, "past_days": min(92, dias), "forecast_days": 1}))
    else:
        peticiones.append((config.archive_url, {**base, "start_date": inicio.isoformat(), "end_date": frontera.isoformat()}))
        dias = max(1, (hoy_utc.date() - frontera).days + 1)
        peticiones.append((config.forecast_url, {**base, "past_days": min(92, dias), "forecast_days": 1}))

    ultimo_error: Exception | None = None
    for intento in range(1, MAX_RETRIES + 1):
        limitador.esperar(1)
        limitador.registrar(1)
        try:
            series = [_serie_desde_respuesta(cliente.weather_api(url, params=params)[0]) for url, params in peticiones]
            return _combinar(series) if len(series) > 1 else series[0]
        except (PresupuestoDiarioAgotado, PresupuestoMensualAgotado):
            raise
        except Exception as exc:  # noqa: BLE001 - se reintenta con backoff
            ultimo_error = exc
            if intento == MAX_RETRIES:
                break
            time.sleep(min(60, 2 ** intento * 2))
    raise RuntimeError(f"La coordenada fallo tras {MAX_RETRIES} intentos: {ultimo_error}")


# ---------------------------------------------------------------------------
# Origen / raiz para unificar y concatenar
# ---------------------------------------------------------------------------
def calcular_origen_id(nombre_fuente: str, coords: pd.DataFrame, col_lon: str, col_lat: str) -> str:
    """Identidad estable de un conjunto de puntos: hash del nombre de la fuente mas el
    conjunto ordenado de coordenadas. Solo archivos con el mismo id se unen."""
    llaves = sorted(f"{str(a).strip()}|{str(b).strip()}" for a, b in zip(coords[col_lat], coords[col_lon]))
    material = nombre_fuente + "::" + "\n".join(llaves)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:12]


def buscar_salidas_previas(result_dir: Path, origen_id: str) -> list[Path]:
    """CSV de result_dir que comparten el mismo origen_id embebido."""
    previas = []
    for csv in sorted(Path(result_dir).glob("clima_*.csv")):
        try:
            cabecera = pd.read_csv(csv, sep="|", nrows=1)
        except Exception:  # noqa: BLE001 - archivo ilegible se ignora
            continue
        if "origen_id" in cabecera.columns and str(cabecera["origen_id"].iloc[0]) == origen_id:
            previas.append(csv)
    return previas


# ---------------------------------------------------------------------------
# Modo B — consulta a puntos (dia o rango), formato ancho, resumible
# ---------------------------------------------------------------------------
def _horas_locales(fecha_inicio: str, fecha_fin: str, tz_name: str) -> list[pd.Timestamp]:
    tz = ZoneInfo(tz_name)
    inicio = pd.Timestamp(fecha_inicio, tz=tz).normalize()
    fin = pd.Timestamp(fecha_fin, tz=tz).normalize() + pd.Timedelta(hours=23)
    return list(pd.date_range(inicio, fin, freq="h"))


def layout_clima_b(modo: str, fecha_inicio: str, fecha_fin: str) -> tuple[list[str], list[str], list[str]]:
    """Devuelve (sufijos, etiquetas_utc, columnas_clima). Los sufijos son la hora local
    (dia: HH; rango: YYYYMMDDHH); las etiquetas_utc son el instante UTC del que se toma el valor."""
    if modo not in {"dia", "rango"}:
        raise ValueError("modo debe ser 'dia' o 'rango'.")
    horas = _horas_locales(fecha_inicio, fecha_fin, BOGOTA_TZ_NAME)
    sufijos = [h.strftime("%H") for h in horas] if modo == "dia" else [h.strftime("%Y%m%d%H") for h in horas]
    etiquetas_utc = [h.tz_convert("UTC").strftime("%Y-%m-%dT%H:00") for h in horas]
    columnas = [f"{corto}_{suf}" for corto in VAR_MAP for suf in sufijos]
    return sufijos, etiquetas_utc, columnas


def coords_pendientes_b(trabajo: pd.DataFrame, columnas_clima: list[str],
                        col_lon: str, col_lat: str) -> int:
    """Cuenta coordenadas unicas que aun tienen clima faltante (para estimar el Gate 3)."""
    pend = trabajo[columnas_clima].isna().any(axis=1)
    if not pend.any():
        return 0
    clave = trabajo.loc[pend, col_lat].astype("string").str.strip() + "|" + trabajo.loc[pend, col_lon].astype("string").str.strip()
    return int(clave.nunique())


def consultar_puntos(fuente: pd.DataFrame, nombre_fuente: str, modo: str, fecha_inicio: str,
                     fecha_fin: str, limitador: LimitadorPersistente, hoy_utc: datetime,
                     config: ConfigAPI, cliente: Any, col_lon: str = COORD_RED[0], col_lat: str = COORD_RED[1],
                     limite_coords: int | None = None, base_previa: pd.DataFrame | None = None) -> pd.DataFrame:
    """Agrega a cada fila las columnas de clima (horas x variables) del ``dia`` o ``rango``.

    Formato ancho. Si ``base_previa`` se pasa, continua esa salida (resume). ``limite_coords``
    procesa solo ese bloque de coordenadas pendientes y deja el resto en NaN (pendiente).
    """
    for col in (col_lon, col_lat):
        if col not in fuente.columns:
            raise ValueError(f"Falta la columna de coordenada {col!r} en la fuente.")

    sufijos, etiquetas_utc, columnas_clima = layout_clima_b(modo, fecha_inicio, fecha_fin)
    utc_ini, utc_fin = etiquetas_utc[0][:10], etiquetas_utc[-1][:10]
    unicas_todas = fuente[[col_lon, col_lat]].drop_duplicates()
    origen_id = calcular_origen_id(nombre_fuente, unicas_todas, col_lon, col_lat)

    if base_previa is not None:
        trabajo = base_previa.copy()
    else:
        trabajo = fuente.copy()
        trabajo = pd.concat([trabajo, pd.DataFrame(np.nan, index=trabajo.index, columns=columnas_clima)], axis=1)
        trabajo["origen_id"] = origen_id
        trabajo["rango_inicio"] = fecha_inicio
        trabajo["rango_fin"] = fecha_fin

    trabajo["_coord_key"] = (
        trabajo[col_lat].astype("string").str.strip() + "|" + trabajo[col_lon].astype("string").str.strip()
    )
    trabajo["_lon"] = pd.to_numeric(trabajo[col_lon], errors="coerce")
    trabajo["_lat"] = pd.to_numeric(trabajo[col_lat], errors="coerce")

    pend_mask = trabajo[columnas_clima].isna().any(axis=1)
    coords_pend = (
        trabajo.loc[pend_mask, ["_coord_key", "_lat", "_lon"]]
        .drop_duplicates("_coord_key").reset_index(drop=True)
    )
    if limite_coords is not None:
        coords_pend = coords_pend.head(limite_coords).copy()

    for _, loc in coords_pend.iterrows():
        if pd.isna(loc["_lat"]) or pd.isna(loc["_lon"]):
            continue
        serie = traer_horario(float(loc["_lat"]), float(loc["_lon"]), utc_ini, utc_fin,
                              limitador, hoy_utc, config, cliente)
        pos = {ts: i for i, ts in enumerate(serie["time"])}
        filas = trabajo["_coord_key"] == loc["_coord_key"]
        for corto, api_var in VAR_MAP.items():
            valores = serie.get(api_var, [])
            for suf, iso_utc in zip(sufijos, etiquetas_utc):
                i = pos.get(iso_utc)
                val = float(valores[i]) if i is not None and i < len(valores) and valores[i] is not None else np.nan
                trabajo.loc[filas, f"{corto}_{suf}"] = val

    return trabajo.drop(columns=["_coord_key", "_lon", "_lat"])


def unificar_por_horas(previo: pd.DataFrame, nuevo: pd.DataFrame, clave: str = "G3E_FID") -> pd.DataFrame:
    """Une dos resultados del MISMO origen sumando las columnas de horas nuevas a las mismas
    filas de puntos. Exige que compartan ``origen_id``."""
    id_prev = set(previo.get("origen_id", pd.Series(dtype=str)).unique())
    id_nuevo = set(nuevo.get("origen_id", pd.Series(dtype=str)).unique())
    if id_prev != id_nuevo:
        raise ValueError(f"origen_id distinto; no se pueden unificar: {id_prev} vs {id_nuevo}.")
    if clave not in previo.columns or clave not in nuevo.columns:
        raise ValueError(f"Falta la clave de punto {clave!r} para unificar.")

    previo, nuevo = previo.copy(), nuevo.copy()
    previo[clave] = previo[clave].astype("string")
    nuevo[clave] = nuevo[clave].astype("string")

    meta = {"rango_inicio", "rango_fin"}
    cols_nuevas = [c for c in nuevo.columns if c not in previo.columns and c not in meta]
    fusion = previo.merge(nuevo[[clave, *cols_nuevas]], on=clave, how="outer")
    fusion["rango_inicio"] = min(str(previo["rango_inicio"].iloc[0]), str(nuevo["rango_inicio"].iloc[0]))
    fusion["rango_fin"] = max(str(previo["rango_fin"].iloc[0]), str(nuevo["rango_fin"].iloc[0]))
    return fusion


def concatenar_salidas(rutas: list[Path], clave: str = "G3E_FID") -> pd.DataFrame:
    """Concatena varias salidas del MISMO origen_id en un unico ancho. Falla si difieren."""
    if not rutas:
        raise ValueError("No hay archivos para concatenar.")
    marcos = [pd.read_csv(r, sep="|") for r in rutas]
    ids = {str(m["origen_id"].iloc[0]) for m in marcos}
    if len(ids) != 1:
        raise ValueError(f"Los archivos no comparten origen_id: {ids}. No se concatenan.")
    acumulado = marcos[0]
    for siguiente in marcos[1:]:
        acumulado = unificar_por_horas(acumulado, siguiente, clave=clave)
    return acumulado


def guardar_resultado(df: pd.DataFrame, ruta: Path) -> Path:
    """Escritura transaccional (.tmp + replace) en formato pipe."""
    ruta = Path(ruta)
    temporal = ruta.with_suffix(".tmp")
    df.to_csv(temporal, sep="|", index=False)
    os.replace(temporal, ruta)
    return ruta


def nombre_salida(nombre_fuente: str, fecha_inicio: str, fecha_fin: str) -> str:
    tallo = Path(nombre_fuente).stem.replace(" ", "_")
    return f"clima_{tallo}_{fecha_inicio}_a_{fecha_fin}.csv"


# ---------------------------------------------------------------------------
# Modo A — actualizar v3 (clima por evento, 25 rezagos) + depuracion
# ---------------------------------------------------------------------------
def _fecha_local_a_utc(serie_str: pd.Series) -> pd.Series:
    dt_local = pd.to_datetime(serie_str, errors="coerce", format=FECHA_FORMAT)
    dt_local = dt_local.dt.tz_localize(ZoneInfo(BOGOTA_TZ_NAME), nonexistent="NaT", ambiguous="NaT")
    return dt_local.dt.tz_convert(timezone.utc)


def columnas_clima_v3() -> list[str]:
    return [f"{corto}_{lag}" for corto in VAR_MAP for lag in range(LAGS)]


def contar_pendientes_v3(v3_path: Path) -> int:
    """Filas de v3 con algun clima faltante (para estimar el Gate 3 del Modo A)."""
    df = pd.read_csv(v3_path)
    cols = columnas_clima_v3()
    faltan = [c for c in cols if c not in df.columns]
    if faltan:
        return len(df)
    return int(df[cols].isna().any(axis=1).sum())


def actualizar_v3(v3_path: Path, cache_dir: Path, hoy_utc: datetime, config: ConfigAPI, cliente: Any,
                  col_lon: str = COORD_V3[0], col_lat: str = COORD_V3[1],
                  limite_filas: int | None = None) -> dict[str, Any]:
    """Completa el clima por evento de las filas nuevas de v3, depura y reescribe v3
    transaccionalmente. Sin filas nuevas, no toca v3 (pasa derecho). ``limite_filas`` procesa
    solo ese bloque maximo y deja el resto pendiente para una proxima corrida."""
    v3_path = Path(v3_path)
    if not v3_path.exists():
        raise FileNotFoundError(f"No existe {v3_path}.")

    df = pd.read_csv(v3_path)
    df.index.name = "original_index"
    for col in ("FECHA", col_lon, col_lat):
        if col not in df.columns:
            raise ValueError(f"Falta la columna requerida {col!r} en v3.")

    df["FECHA"] = pd.to_datetime(df["FECHA"], errors="coerce").dt.strftime(FECHA_FORMAT)
    evento_utc = _fecha_local_a_utc(df["FECHA"].astype(str))
    if evento_utc.isna().any():
        raise ValueError("Hay fechas invalidas en FECHA; revisa esas filas antes de consultar la API.")

    columnas_clima = columnas_clima_v3()
    faltan = [c for c in columnas_clima if c not in df.columns]
    if faltan:  # se agregan de un saque para no fragmentar el frame (v3 es grande)
        df = pd.concat([df, pd.DataFrame(np.nan, index=df.index, columns=faltan)], axis=1)

    pendientes = df.index[df[columnas_clima].isna().any(axis=1)].tolist()
    total_pendientes = len(pendientes)
    if limite_filas is not None:
        pendientes = pendientes[:limite_filas]

    if not pendientes:
        return {"actualizado": False, "filas_nuevas": 0, "restantes": 0,
                "mensaje": "Sin filas nuevas: v3 intacto (pasa derecho)."}

    limitador = crear_limitador(cache_dir, config)
    completadas = 0
    for idx in pendientes:
        lon = pd.to_numeric(df.at[idx, col_lon], errors="coerce")
        lat = pd.to_numeric(df.at[idx, col_lat], errors="coerce")
        ev = evento_utc.loc[idx]
        if pd.isna(lon) or pd.isna(lat) or pd.isna(ev):
            continue
        hora_evento = ev.to_pydatetime().replace(minute=0, second=0, microsecond=0)
        inicio = (hora_evento - timedelta(hours=LAGS - 1)).date().isoformat()
        fin = hora_evento.date().isoformat()
        serie = traer_horario(float(lat), float(lon), inicio, fin, limitador, hoy_utc, config, cliente)
        pos = {ts: i for i, ts in enumerate(serie["time"])}
        deseados = [(hora_evento - timedelta(hours=lag)).strftime("%Y-%m-%dT%H:00") for lag in range(LAGS)]
        lleno = False
        for corto, api_var in VAR_MAP.items():
            valores = serie.get(api_var, [])
            for lag, iso in enumerate(deseados):
                col = f"{corto}_{lag}"
                if pd.isna(df.at[idx, col]):
                    i = pos.get(iso)
                    if i is not None and i < len(valores) and valores[i] is not None:
                        df.at[idx, col] = float(valores[i])
                        lleno = True
        if lleno:
            completadas += 1

    _depurar_v3(df)
    guardar_resultado_csv_coma(df, v3_path)
    restantes = total_pendientes - len(pendientes)
    return {"actualizado": True, "filas_nuevas": len(pendientes), "filas_completadas": completadas,
            "restantes": restantes,
            "mensaje": f"v3 actualizado: {completadas} filas nuevas con clima; {restantes} pendientes."}


def _depurar_v3(df: pd.DataFrame) -> None:
    faltantes = [c for c in (*NUMERIC_ZERO_FILL, *TEXT_ZERO_FILL, FECHA_TRF_COL, FECHA_VANO_COL, ALTURA_COL)
                 if c not in df.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas para la depuracion final: {faltantes}")
    for col in NUMERIC_ZERO_FILL:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col in TEXT_ZERO_FILL:
        blanco = df[col].isna() | df[col].astype(str).str.strip().eq("")
        df[col] = df[col].mask(blanco, "0")
    blanco_trf = df[FECHA_TRF_COL].isna() | df[FECHA_TRF_COL].astype(str).str.strip().eq("")
    df.loc[blanco_trf, FECHA_TRF_COL] = df.loc[blanco_trf, FECHA_VANO_COL]
    df.drop(index=df.index[df[ALTURA_COL].isna()], inplace=True)


def guardar_resultado_csv_coma(df: pd.DataFrame, ruta: Path) -> Path:
    """Escritura transaccional de v3 en formato coma (como el cuaderno original)."""
    ruta = Path(ruta)
    temporal = ruta.with_suffix(".tmp")
    df.to_csv(temporal, index=False)
    os.replace(temporal, ruta)
    return ruta
