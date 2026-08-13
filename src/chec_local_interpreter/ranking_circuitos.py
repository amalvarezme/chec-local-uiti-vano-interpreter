"""El ranking de circuitos por vanos criticos, portado del cuaderno 02.

El informe abria con el agrupamiento de CIRCUITOS: una nube de 208 puntos, eventos contra
UITI acumulado. Responde "de que tamano es este circuito comparado con los demas", que no
es la pregunta operativa. La pregunta es **cuantos vanos criticos tiene**: un circuito
chico con cuarenta vanos en Medio-Alto se atiende antes que uno grande con tres, y en la
nube los dos son un punto y no hay manera de verlo.

Esto es el segundo tablero del cuaderno 02, en Python: agrupamiento a nivel de VANO y,
por circuito, el conteo de sus vanos en Medio-Alto mas Alto. Se porta VERBATIM -- mismo
espacio (eje x lineal, eje y en log10), mismo escalador minmax, misma semilla, mismos
cortes P50/P75/P97 -- porque dos implementaciones del mismo ranking se separan en cuanto
alguien toca una, y entonces el tablero y el informe ordenan los circuitos distinto sin
que nada en pantalla lo diga.

El conteo suma Medio-Alto Y Alto a proposito: un circuito con muchos vanos a un paso de
la clase peor es tan accionable como uno que ya los tiene ahi -- mas, porque esa poblacion
todavia se puede evitar --, y mirando solo Alto queda invisible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

# Los cuatro grupos de VANO, nombrados por el ranking de la mediana del UITI acumulado.
NOMBRES_GRUPOS_VANO: tuple[str, ...] = ("Bajo", "Medio", "Medio-Alto", "Alto")
# Indices de los dos grupos que el ranking cuenta.
GRUPOS_CRITICOS: tuple[int, ...] = (2, 3)

# Las cuatro bandas de RIESGO del circuito. Nombradas por riesgo y no por percentil: "P75"
# no le dice nada a quien opera la red, y el numero del corte sigue disponible aparte.
NOMBRES_RANGO: tuple[str, ...] = (
    "Riesgo Bajo", "Riesgo Medio", "Riesgo Medio-Alto", "Riesgo Alto",
)
# El mismo semaforo de los cuadernos, en `rgb(...)` porque el relleno translucido sale de
# `.replace('rgb', 'rgba')`, que sobre un hexadecimal no encuentra nada y falla en silencio.
COLORES_RANGO: tuple[str, ...] = (
    "rgb(26,150,65)", "rgb(242,194,0)", "rgb(239,108,0)", "rgb(198,40,40)",
)

# P50/P75/P97 y no cuartiles: la distribucion tiene una cola larga a la derecha, y con
# 25/50/75 la ultima banda se lleva un cuarto de los circuitos, mezclando los
# verdaderamente criticos con los del monton. Con P97 el Riesgo Alto queda en el 3%
# superior, que es lo accionable.
PERCENTILES_RANGO: tuple[float, float, float] = (50.0, 75.0, 97.0)

SEMILLA = 42
# Eje x (numero de eventos) lineal y eje y (UITI acumulado) en log10: el UITI abarca
# varios ordenes de magnitud y en lineal los grupos bajos se apilan contra el cero.
LOG_X, LOG_Y = False, True

_COLUMNAS_REQUERIDAS = {"CIRCUITO", "FID_VANO", "UITI_VANO"}


@dataclass(frozen=True)
class RankingCircuitos:
    """El ranking listo para dibujar y para citar.

    `tabla` va en el orden en que se dibujan las barras -- de menor a mayor conteo --, y
    `posicion` es el puesto por criticidad (1 = el peor), que es lo que se cita en prosa.
    Los dos ordenes conviven porque responden cosas distintas y derivar uno del otro en el
    sitio equivocado es como el informe termina diciendo "puesto 1" del circuito mas
    tranquilo.
    """

    tabla: pd.DataFrame
    cortes: tuple[float, float, float]
    geometria: dict[str, Any]
    circuitos_sin_eventos: int
    circuitos_en_cero: int


def _normalizar_fid(serie: pd.Series) -> pd.Series:
    """`FID_VANO` llega numerico con sufijo `.0` inconsistente entre filas.

    Sin normalizar, `20130434` y `20130434.0` son dos vanos con la mitad de los eventos
    cada uno, y los dos caen en un grupo mas bajo del que les toca. Misma regla que
    `plotting._norm_map_id`.
    """
    return (serie.astype("string").str.strip().str.replace(r"\.0$", "", regex=True))


def _por_vano(df: pd.DataFrame) -> pd.DataFrame:
    """Eventos y UITI acumulado por vano. El evento es una FILA, no una fecha distinta:
    es la unidad de este tablero, a diferencia del de circuitos, donde una misma salida
    golpea muchos vanos y cuenta una sola vez."""
    trabajo = pd.DataFrame({
        "CIRCUITO": df["CIRCUITO"].astype(str),
        "FID_VANO": _normalizar_fid(df["FID_VANO"]),
        "UITI_VANO": pd.to_numeric(df["UITI_VANO"], errors="coerce").fillna(0.0),
    })
    return (trabajo.groupby(["CIRCUITO", "FID_VANO"], observed=True)["UITI_VANO"]
            .agg(uiti="sum", eventos="count").reset_index())


def _recortar(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    if start_date is None and end_date is None:
        return df
    if "FECHA" not in df.columns:
        return df
    fecha = pd.to_datetime(df["FECHA"], errors="coerce").dt.floor("D")
    dentro = pd.Series(True, index=df.index)
    if start_date is not None:
        dentro &= fecha >= pd.to_datetime(start_date).floor("D")
    if end_date is not None:
        dentro &= fecha <= pd.to_datetime(end_date).floor("D")
    return df[dentro]


def geometria_vanos(raw_df: pd.DataFrame) -> dict[str, Any]:
    """La particion del plano de vanos, ajustada UNA vez sobre el rango COMPLETO.

    Los centroides quedan fijos. Si cada ventana reajustara K-Means, "Alto" significaria
    una cosa distinta en cada corrida y dos informes del mismo circuito no serian
    comparables: cambiar el periodo movería los circuitos Y las fronteras a la vez, y no
    habria forma de saber cual de las dos cosas produjo la diferencia.
    """
    if raw_df is None or raw_df.empty or not _COLUMNAS_REQUERIDAS <= set(raw_df.columns):
        return {}

    from sklearn.cluster import KMeans
    from sklearn.preprocessing import MinMaxScaler

    vanos = _por_vano(raw_df)
    vanos = vanos[(vanos["eventos"] > 0) & (vanos["uiti"] > 0)]
    if len(vanos) < len(NOMBRES_GRUPOS_VANO):
        return {}

    X = _espacio(vanos["eventos"].to_numpy(float), vanos["uiti"].to_numpy(float))
    escalador = MinMaxScaler().fit(X)
    modelo = KMeans(n_clusters=len(NOMBRES_GRUPOS_VANO), random_state=SEMILLA,
                    n_init=10).fit(escalador.transform(X))

    offset = np.round(escalador.data_min_, 6)
    scale = np.round(escalador.data_range_, 6)
    centros = np.round(modelo.cluster_centers_, 6)

    # El id que devuelve K-Means es arbitrario: el nombre del grupo se asigna por el
    # ranking de la MEDIANA del UITI acumulado, de menor a mayor. Reordenar los centroides
    # no cambia cual es el mas cercano, asi que la pertenencia sigue siendo la misma.
    crudos = _mas_cercano(X, centros, offset, scale)
    uiti = vanos["uiti"].to_numpy(float)
    orden = list(np.argsort([
        np.median(uiti[crudos == c]) if np.any(crudos == c) else np.inf
        for c in range(len(NOMBRES_GRUPOS_VANO))
    ]))
    return {
        "logs": [bool(LOG_X), bool(LOG_Y)],
        "offset": offset.tolist(),
        "scale": scale.tolist(),
        "centroides": centros[orden].tolist(),
    }


def _espacio(eventos: np.ndarray, uiti: np.ndarray) -> np.ndarray:
    X = np.column_stack([np.asarray(eventos, float), np.asarray(uiti, float)])
    if LOG_X:
        X[:, 0] = np.log10(X[:, 0])
    if LOG_Y:
        X[:, 1] = np.log10(X[:, 1])
    return X


def _mas_cercano(X, centroides, offset, scale) -> np.ndarray:
    scale = np.where(np.asarray(scale, float) == 0, 1e-9, np.asarray(scale, float))
    Z = (np.asarray(X, float) - np.asarray(offset, float)) / scale
    centroides = np.asarray(centroides, float)
    return ((Z[:, None, :] - centroides[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)


def grupo_de_vanos(
    eventos: np.ndarray, uiti: np.ndarray, geometria: dict[str, Any]
) -> np.ndarray:
    """El grupo de cada vano por centroide mas cercano, la misma regla que el JS del
    cuaderno. Sin compartirla, el informe podria pintar un vano de un grupo y el tablero
    de otro sobre exactamente los mismos numeros."""
    if not geometria:
        return np.zeros(len(np.atleast_1d(eventos)), dtype=int)
    return _mas_cercano(_espacio(eventos, uiti), geometria["centroides"],
                        geometria["offset"], geometria["scale"])


def _percentil(valores: np.ndarray, q: float) -> float:
    """Interpolacion lineal, el metodo por defecto de numpy: es el que reimplementa el JS
    del cuaderno, asi que los cortes coinciden valor por valor."""
    return float(np.percentile(valores, q)) if len(valores) else 0.0


def ranking_circuitos(
    raw_df: pd.DataFrame,
    start_date: Any = None,
    end_date: Any = None,
    *,
    geometria: dict[str, Any] | None = None,
) -> RankingCircuitos:
    """Los circuitos ordenados por sus vanos en Medio-Alto mas Alto, en la ventana pedida.

    Entran TODOS los circuitos de la base, incluidos los que no registraron un solo evento
    en la ventana: quedan en cero, a la izquierda, y CUENTAN para los percentiles.
    Excluirlos sesga los cortes hacia arriba -- tanto mas cuanto mas corta la ventana -- y
    el circuito estudiado aparece mejor situado de lo que esta.
    """
    columnas = ["circuito", "vanos_criticos", "vanos_medio_alto", "vanos_alto",
                "vanos_con_eventos", "uiti_total", "eventos_total", "rango_idx",
                "rango", "color", "posicion"]
    if raw_df is None or raw_df.empty or not _COLUMNAS_REQUERIDAS <= set(raw_df.columns):
        return RankingCircuitos(pd.DataFrame(columns=columnas), (0.0, 0.0, 0.0), {}, 0, 0)

    geometria = geometria_vanos(raw_df) if geometria is None else geometria
    universo = sorted(raw_df["CIRCUITO"].astype(str).unique().tolist())

    vanos = _por_vano(_recortar(raw_df, start_date, end_date))
    vanos = vanos[(vanos["eventos"] > 0) & (vanos["uiti"] > 0)]
    if vanos.empty:
        conteos = pd.DataFrame(0, index=universo,
                               columns=list(range(len(NOMBRES_GRUPOS_VANO))))
        agregados = pd.DataFrame(0.0, index=universo, columns=["uiti", "eventos", "vanos"])
    else:
        vanos = vanos.assign(grupo=grupo_de_vanos(
            vanos["eventos"].to_numpy(float), vanos["uiti"].to_numpy(float), geometria))
        conteos = (vanos.pivot_table(index="CIRCUITO", columns="grupo", values="FID_VANO",
                                     aggfunc="count", fill_value=0)
                   .reindex(universo, fill_value=0)
                   .reindex(columns=range(len(NOMBRES_GRUPOS_VANO)), fill_value=0))
        agregados = (vanos.groupby("CIRCUITO")
                     .agg(uiti=("uiti", "sum"), eventos=("eventos", "sum"),
                          vanos=("FID_VANO", "count"))
                     .reindex(universo, fill_value=0))

    criticos = conteos[list(GRUPOS_CRITICOS)].sum(axis=1).astype(int)
    tabla = pd.DataFrame({
        "circuito": universo,
        "vanos_criticos": criticos.to_numpy(),
        "vanos_medio_alto": conteos[2].to_numpy().astype(int),
        "vanos_alto": conteos[3].to_numpy().astype(int),
        "vanos_con_eventos": agregados["vanos"].to_numpy().astype(int),
        "uiti_total": agregados["uiti"].to_numpy().astype(float).round(2),
        "eventos_total": agregados["eventos"].to_numpy().astype(int),
    })
    # De menor a mayor, que es el orden en que se dibujan las barras. Desempate por
    # nombre para que dos corridas sobre los mismos datos den el mismo grafico.
    tabla = tabla.sort_values(["vanos_criticos", "circuito"], kind="stable").reset_index(drop=True)

    valores = tabla["vanos_criticos"].to_numpy(float)
    cortes = tuple(_percentil(valores, q) for q in PERCENTILES_RANGO)
    rango_idx = np.digitize(valores, list(cortes), right=True)
    tabla["rango_idx"] = rango_idx.astype(int)
    tabla["rango"] = [NOMBRES_RANGO[i] for i in tabla["rango_idx"]]
    tabla["color"] = [COLORES_RANGO[i] for i in tabla["rango_idx"]]
    # Puesto por criticidad, 1 = el peor. Es lo que se cita en prosa, y es el orden
    # INVERSO al de dibujo: derivarlo en el sitio equivocado es como el informe termina
    # anunciando "puesto 1" del circuito mas tranquilo.
    tabla["posicion"] = tabla["vanos_criticos"].rank(method="min", ascending=False).astype(int)

    return RankingCircuitos(
        tabla=tabla[columnas],
        cortes=cortes,
        geometria=geometria,
        circuitos_sin_eventos=int((tabla["vanos_con_eventos"] == 0).sum()),
        circuitos_en_cero=int((tabla["vanos_criticos"] == 0).sum()),
    )
