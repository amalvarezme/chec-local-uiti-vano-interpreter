"""El tablero de trayectorias de circuito, con ventana deslizante.

## De donde sale este modulo

Es el cuaderno `03_uiti_vano_trayectorias_circuitos.ipynb`, movido aqui. Ver
`chec_tableros.clima` para el porque del traslado y para el criterio de reparto
entre constantes de modulo y tuberia dentro de `construir()`.

## Lo unico que cambia respecto del cuaderno

- `display(HTML(...))` desaparece: no hay kernel ni celda donde pintar.
- `REPO_ROOT`, el destino del HTML y el abrir-en-navegador los pasa quien llama.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import pyarrow.csv as pacsv
from plotly.subplots import make_subplots
from sklearn.cluster import KMeans
from sklearn.preprocessing import MinMaxScaler, StandardScaler

# Ademas de pintar el panel dentro del cuaderno, escribe el mismo HTML autocontenido en
# reports/paneles/ y lo abre en el navegador, donde el tablero usa todo el ancho de la
# pantalla. En Databricks se pone en False: dentro de un job no hay navegador.

NOMBRES_GRUPOS = ['Bajo', 'Medio', 'Medio-Alto', 'Alto']
# Paleta Reds, de claro a oscuro, para que el color ordene los grupos por criticidad.
# Semaforo: verde Bajo, amarillo Medio, naranja Medio-Alto, rojo Alto. Antes era una
# rampa de rojos, que ordenaba por SATURACION: `Bajo` y `Medio` eran dos rosas que solo
# se distinguian mirandolos uno al lado del otro, y en el mapa el mas claro quedaba a un
# paso del fondo. El semaforo ordena por TONO, que es lo que se lee de un vistazo y sin
# tener la leyenda al lado.
# Contraste medido contra el fondo de carto-positron (#f2f0eb): 3,36 / 1,48 / 2,71 / 4,94.
# El amarillo es el mas flojo de los cuatro, pero el peor caso NO empeora -- el `Bajo`
# salmon de la rampa vieja medía 1,44 --, y oscurecerlo mas lo acerca al naranja hasta
# volver indistinguibles los dos niveles del medio.
# En formato `rgb(...)` y no hexadecimal a proposito: el relleno de los violines y de los
# contornos sale de `.replace('rgb', 'rgba')`, que sobre un hex no encuentra nada y deja
# el relleno sin aplicar, en silencio.
COLORES_GRUPOS = ['rgb(26,150,65)', 'rgb(242,194,0)', 'rgb(239,108,0)', 'rgb(198,40,40)']
PREPROCESOS = {'minmax': MinMaxScaler, 'zscore': StandardScaler}
SIN_SELECCION = '(ninguno)'
SEMILLA = 42
# La nube tiene DOS niveles de opacidad y no una cascada de tres. El sujeto de la figura
# es un par circuito x ventana, asi que ese par -- y solo ese -- va opaco; todo lo demas
# queda de fondo, ya sea otro circuito, otra ventana, o las dos cosas. Un tercer nivel
# intermedio obligaba a recordar que significaba cada tono, y con la pregunta reducida a
# "cual es el punto de interes" no hay nada que graduar.
# Sin circuito elegido no hay interseccion posible, y ahi manda la ventana sola: si no, la
# nube entera quedaria uniformemente de fondo y el deslizador no diria nada.
OPACIDAD_FOCO = 1.0
OPACIDAD_FONDO = 0.30

# La evolucion por ventana usa una paleta distinta de la de los grupos. Sus lineas indican
# que variable es cada serie, no el nivel de criticidad; el color de criticidad queda
# reservado al marcador, que se pinta con el grupo en que cayo el circuito en esa ventana.
COLOR_LINEA_UITI = '#1d4ed8'
COLOR_LINEA_EVENTOS = '#0f766e'
COLOR_SIN_GRUPO = '#94a3b8'
# El punto de la VENTANA VIGENTE en las dos series del doble eje se dibuja al triple, como
# el dia vigente en la serie del cuaderno 01. `marker.size` es un ARRAY por eso: mover el
# deslizador solo reescribe ese arreglo y el punto grande viaja con el.
SERIE_TAM_UITI = 10
SERIE_TAM_EVENTOS = 9
FACTOR_PUNTO_ACTIVO = 3


# Sube desde el directorio actual hasta encontrar data/Indicadores_vano_v3.csv, para que el
# cuaderno funcione sin importar desde donde se ejecute.
def find_repo_root():
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / 'data/Indicadores_vano_v3.csv').exists():
            return candidate
    raise FileNotFoundError('No se encontro data/Indicadores_vano_v3.csv subiendo desde el cwd')

# El mapa usa la MISMA paleta que el agrupamiento, no una escala aparte, para que un color
# signifique lo mismo en las dos vistas del tablero y entre este cuaderno y el 04. La
# diferencia de fondo: aqui el K-Means corre sobre CIRCUITO x ventana, de modo que un vano no
# tiene grupo propio y su color sale de cortes fijos de UITI. En el 04, donde la unidad si es
# el vano, el color del mapa es la membresia de K-Means.
CLASES_MAPA = NOMBRES_GRUPOS
COLORES_MAPA = COLORES_GRUPOS
COLOR_SIN_EVENTO = 'rgb(0,0,0)'
# Anchos del mapa, con los mismos nombres y valores que el 04, para que un vano sin eventos
# se vea igual en los dos cuadernos.
# Estilo del mapa, TOMADO DEL CUADERNO 01 (`01_uiti_vano_clima`, celda 4). Los cuatro
# mapas del proyecto dibujan los mismos objetos sobre la misma geografia, asi que un
# transformador, un vano con eventos y uno sin ellos tienen que medir lo mismo en todos:
# de otro modo el mismo circuito se lee como dos circuitos distintos al pasar de cuaderno.
# 01 subio los equipos de 6/5 a 14/12 px y la capa de vano de 3.5 a 7.0 px cuando su figura
# doblo de alto; aqui se adoptan esos valores, que es lo que hace comparables los mapas.
# Contrapartida: este mapa es mas bajo que el de 01, asi que el mismo trazo pesa mas sobre
# el. Se asume: la comparacion entre cuadernos vale mas que el equilibrio de cada uno.
ANCHO_MAPA = 7.0                 # vano CON eventos, del color de su grupo
ANCHO_SIN_EVENTOS = 1.5          # estructura del circuito: el vano sin eventos
COLOR_TRAFO = '#f59e0b'
COLOR_SWITCH = '#7c3aed'
TAM_TRAFO = 14
TAM_SWITCH = 12




def _corta(ruta: Path, raiz: Path) -> str:
    """La ruta relativa al repositorio, o la absoluta si cae fuera.

    `construir()` acepta cualquier `ruta_html`, asi que el destino no tiene por que
    estar dentro del arbol -- un directorio temporal, uno de despliegue. Con
    `Path.relative_to` a secas eso era un `ValueError` lanzado DESPUES de construir el
    tablero entero: el archivo quedaba escrito y la llamada fallaba igual.

    La raiz entra por argumento porque `REPO_ROOT` es local de `construir()`: se
    resuelve por llamada, ya que puede venir dada.
    """
    try:
        return str(ruta.relative_to(raiz))
    except ValueError:
        return str(ruta)

def construir(*, raiz=None, ruta_html=None, abrir: bool = False) -> Path:
    """Construye el tablero y devuelve la ruta del HTML autocontenido."""
    ABRIR_EN_NAVEGADOR = bool(abrir)

    REPO_ROOT = Path(raiz) if raiz is not None else find_repo_root()

    # FID_VANO hace falta para contar vanos unicos por grupo; el CSV completo trae ~270 columnas.
    COLUMNAS_BASE = ['CIRCUITO', 'FID_VANO', 'UITI_VANO', 'FECHA']


    def leer_eventos(columnas=COLUMNAS_BASE):
        """Lee el CSV de eventos por bloques y devuelve solo `columnas`, en ese orden.

    Se usa el lector incremental de pyarrow en vez de `pd.read_csv`. El resultado es el
    mismo valor por valor, pero `pd.read_csv(engine='pyarrow')` materializa el archivo de
    566 MB antes de descartar las columnas que no se usan: medido, 826 MB de pico de
    memoria contra 109 MB por bloques, a cambio de 0,2 s mas de lectura.
    """
        lector = pacsv.open_csv(
            str(REPO_ROOT / 'data' / 'Indicadores_vano_v3.csv'),
            convert_options=pacsv.ConvertOptions(include_columns=list(columnas)),
        )
        return lector.read_all().to_pandas()


    df = leer_eventos()
    # pyarrow ya entrega FECHA como fecha y UITI_VANO como numero; las conversiones quedan por
    # si el archivo cambia de tipos.
    df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
    df['UITI_VANO'] = pd.to_numeric(df['UITI_VANO'], errors='coerce').fillna(0.0)


    # FID_VANO llega numerico, con sufijo '.0' inconsistente entre filas. Se normaliza como
    # texto igual que `chec_local_interpreter.plotting._norm_map_id`, para no duplicar vanos por
    # formato. Vive aqui y no en la celda del mapa porque las dos vistas deben normalizar
    # IGUAL: el cruce con la geometria se hace por este valor, y dos criterios distintos
    # dejarian vanos sin correspondencia en silencio, sin que nada falle.
    def _norm_id(serie):
        return (serie.astype('string').str.strip().str.replace(r'\.0$', '', regex=True)
                .replace({'': pd.NA, '<NA>': pd.NA, 'nan': pd.NA, 'None': pd.NA}))


    df['FID_VANO'] = _norm_id(df['FID_VANO'])

    CIRCUITOS = sorted(df['CIRCUITO'].unique())
    # El panel ya no deja elegir la escala de los ejes ni el preproceso. El eje Y va en
    # logaritmica -- el UITI acumulado abarca varios ordenes de magnitud, y en lineal las
    # ventanas tranquilas se apilan contra el cero --, el eje X lineal y el escalador minmax.
    # Antes se precomputaban las ocho combinaciones para que el selector saltara entre ellas
    # sin recalcular; con una sola, K-Means se ajusta UNA vez en vez de ocho. La lista se
    # conserva con un elemento porque todo lo que viene abajo indexa por espacio y el JS busca
    # su geometria por esa clave.
    LOG_X, LOG_Y, PREPROCESO = False, True, 'minmax'
    ESPACIOS = [(LOG_X, LOG_Y, PREPROCESO)]
    IDX_ESPACIO_DEFECTO = 0

    # Cada mes aporta DOS ventanas: el mes calendario completo y la cruzada, que va del dia 15
    # de ese mes al 15 del siguiente. Ordenadas por fecha de inicio quedan alternadas
    # (mes completo, cruzada, mes completo, ...) y el paso efectivo es de medio mes.
    _meses = pd.period_range(df['FECHA'].min(), df['FECHA'].max(), freq='M')
    _fin_datos = _meses[-1].to_timestamp(how='end').normalize() + pd.Timedelta(days=1)

    # Intervalos semiabiertos [desde, hasta_excl): el dia 15 pertenece a la ventana que arranca
    # en el, de modo que el solape no cuenta dos veces un evento que cae justo en el borde.
    _cortes = []
    for _k, _m in enumerate(_meses):
        _ini = _m.to_timestamp()
        _fin = _meses[_k + 1].to_timestamp() if _k + 1 < len(_meses) else _fin_datos
        _cortes.append((_ini, _fin))
        _cortes.append((_ini + pd.Timedelta(days=14), _fin + pd.Timedelta(days=14)))
    # Una ventana que se pasa del final de la base quedaria corta y dibujaria una caida falsa.
    _cortes = sorted(c for c in _cortes if c[1] <= _fin_datos)

    VENTANAS = [
        {
            'i': k,
            'desde': desde,
            'hasta_excl': hasta,
            'etiqueta': f'V{k + 1}',
            'periodo': f'{desde.date()} a {(hasta - pd.Timedelta(days=1)).date()}',
        }
        for k, (desde, hasta) in enumerate(_cortes)
    ]

    print(f'{len(df):,} eventos | {len(CIRCUITOS)} circuitos | '
          f'{df["FID_VANO"].nunique():,} vanos | '
          f'{df["FECHA"].min():%Y-%m-%d} a {df["FECHA"].max():%Y-%m-%d}')
    for v in VENTANAS:
        _dias = (v['hasta_excl'] - v['desde']).days
        print(f'  {v["etiqueta"]:>3s}  {v["periodo"]}  ({_dias} dias)')

    # La ultima media luna de datos no completa una ventana. Se informa en vez de incluirla como
    # ventana corta: una ventana con la mitad de dias mostraria una caida que no existe.
    _cola = VENTANAS[-1]['hasta_excl']
    _eventos_cola = int((df['FECHA'] >= _cola).sum())
    if _eventos_cola:
        # Un print() vacio en vez de un salto embebido: este texto pasa por un string no-raw del
        # generador y una sola barra se convertiria en salto de linea real, rompiendo la celda.
        print()
        print(f'FUERA DE VENTANA: {_cola.date()} a {df["FECHA"].max():%Y-%m-%d} -- '
              f'{_eventos_cola:,} eventos ({100 * _eventos_cola / len(df):.1f}% de la base) '
              f'no entran en ninguna ventana completa.')


    def tabla_ventanas():
        """UITI acumulado y numero de eventos por circuito y ventana, grilla completa.

    Devuelve todas las ventanas para los 208 circuitos, con ceros donde no hubo eventos:
    una grilla regular es mas facil de consumir aguas abajo que una tabla rala.
    """
        piezas = []
        for v in VENTANAS:
            dentro = df[(df['FECHA'] >= v['desde']) & (df['FECHA'] < v['hasta_excl'])]
            agregado = (
                dentro.groupby('CIRCUITO')
                # Un evento es una FECHA distinta dentro de la ventana, no una fila: una misma
                # salida afecta a muchos vanos. Misma definicion que el agrupamiento de
                # circuitos del reporte (`count_unique_event_dates`).
                .agg(uiti_acumulado=('UITI_VANO', 'sum'), num_eventos=('FECHA', 'nunique'))
                .reindex(CIRCUITOS)                       # reindex trae los circuitos ausentes
                .fillna({'uiti_acumulado': 0.0, 'num_eventos': 0})
                .reset_index(names='circuito')
            )
            agregado.insert(1, 'ventana', v['etiqueta'])
            agregado.insert(2, 'desde', str(v['desde'].date()))
            agregado.insert(3, 'hasta', str((v['hasta_excl'] - pd.Timedelta(days=1)).date()))
            piezas.append(agregado)

        tabla = pd.concat(piezas, ignore_index=True)
        tabla['num_eventos'] = tabla['num_eventos'].astype(int)
        tabla['uiti_acumulado'] = tabla['uiti_acumulado'].round(2)
        # Orden circuito -> ventana cronologica: es el orden en que se recorren las flechas.
        tabla['_orden'] = tabla['ventana'].map({v['etiqueta']: v['i'] for v in VENTANAS})
        return (tabla.sort_values(['circuito', '_orden'])
                     .drop(columns='_orden')
                     .reset_index(drop=True))


    TABLA = tabla_ventanas()
    vacias = int((TABLA['num_eventos'] == 0).sum())
    print(f'{len(TABLA)} filas = {len(CIRCUITOS)} circuitos x {len(VENTANAS)} ventanas '
          f'| sin eventos: {vacias} ({100 * vacias / len(TABLA):.1f}%)')
    TABLA.head(12)

    # --- celdas de la nube -------------------------------------------------------------------
    POR_CIRCUITO = {
        circuito: {'n': grupo['num_eventos'].tolist(), 'u': grupo['uiti_acumulado'].tolist()}
        for circuito, grupo in TABLA.groupby('circuito', sort=True)
    }

    # Orden canonico de las celdas con eventos: circuito y despues ventana. El JS reconstruye
    # esta misma secuencia, de modo que las etiquetas de grupo se alinean sin enviar indices. Si
    # los dos recorridos divergieran, los colores de la nube no corresponderian.
    CELDAS = [(ci, vi)
              for ci, circuito in enumerate(CIRCUITOS)
              for vi in range(len(VENTANAS))
              if POR_CIRCUITO[circuito]['n'][vi] > 0]
    XY = np.array([[POR_CIRCUITO[CIRCUITOS[ci]]['n'][vi],
                    POR_CIRCUITO[CIRCUITOS[ci]]['u'][vi]] for ci, vi in CELDAS], dtype=float)

    # --- vanos por celda, para contar los unicos de cada grupo -------------------------------
    _piezas = []
    for v in VENTANAS:
        dentro = df[(df['FECHA'] >= v['desde']) & (df['FECHA'] < v['hasta_excl'])]
        par = dentro[['CIRCUITO', 'FID_VANO']].drop_duplicates()
        par = par.assign(ventana_i=v['i'])
        _piezas.append(par)
    CELDA_VANOS = pd.concat(_piezas, ignore_index=True)
    _indice_circuito = {c: i for i, c in enumerate(CIRCUITOS)}
    CELDA_VANOS['celda'] = (CELDA_VANOS['CIRCUITO'].map(_indice_circuito).astype(int) * len(VENTANAS)
                            + CELDA_VANOS['ventana_i'].astype(int))
    _clave_celda = {ci * len(VENTANAS) + vi: k for k, (ci, vi) in enumerate(CELDAS)}


    def aplicar_log(X, logs):
        """log10 columna por columna, segun que ejes lo tengan activado."""
        V = np.array(X, dtype=float, copy=True)
        for c, activo in enumerate(logs):
            if activo:
                V[:, c] = np.log10(V[:, c])
        return V


    def agrupar_celdas(logs, prep):
        """K-Means a 4 grupos sobre las celdas con eventos, en el espacio ajustado.

    Devuelve las etiquetas y la geometria de la particion (centroides y parametros del
    escalador), que es lo que necesitan los contornos de membresia.
    """
        X = aplicar_log(XY, logs)
        escalador = PREPROCESOS[prep]().fit(X)
        modelo = KMeans(n_clusters=4, random_state=SEMILLA, n_init=10).fit(escalador.transform(X))
        etiquetas = modelo.labels_

        # El id que devuelve K-Means es arbitrario. El nombre del grupo se asigna por el
        # ranking de la MEDIANA del UITI acumulado, de menor a mayor.
        medianas = [np.median(XY[etiquetas == c, 1]) for c in range(4)]
        orden = list(np.argsort(medianas))
        remapeo = {c: i for i, c in enumerate(orden)}

        # Todo escalador se reduce a (v - offset) / scale, de modo que el JS aplica uno solo.
        if prep == 'minmax':
            offset, scale = escalador.data_min_, escalador.data_range_
        else:
            offset, scale = escalador.mean_, escalador.scale_

        geometria = {
            'logs': [bool(logs[0]), bool(logs[1])],
            'offset': np.round(offset, 6).tolist(),
            'scale': np.round(scale, 6).tolist(),
            'centroides': np.round(modelo.cluster_centers_[orden], 6).tolist(),
        }
        return np.array([remapeo[c] for c in etiquetas], dtype=int), geometria


    def membresia(X_display, geometria):
        """Grupo de cada punto por centroide mas cercano; replica en numpy lo que hace el JS."""
        Z = ((aplicar_log(X_display, geometria['logs']) - np.array(geometria['offset']))
             / np.array(geometria['scale']))
        d = ((Z[:, None, :] - np.array(geometria['centroides'])[None, :, :]) ** 2).sum(axis=2)
        return d.argmin(axis=1)


    # Extremos en unidades originales: con ellos el JS arma la grilla del contorno. No dependen
    # del espacio, porque las celdas son siempre las mismas; lo que cambia es la transformacion.
    EXTENSION = [float(XY[:, 0].min()), float(XY[:, 0].max()),
                 float(XY[:, 1].min()), float(XY[:, 1].max())]

    GRUPOS_POR_ESPACIO, VANOS_POR_GRUPO, GEOMETRIAS = {}, {}, {}
    for e, (log_x, log_y, prep) in enumerate(ESPACIOS):
        grupos, geometria = agrupar_celdas((log_x, log_y), prep)

        # El contorno se dibuja con la regla de centroide mas cercano, no con las etiquetas. Si
        # esa regla no reprodujera la particion de scikit-learn, la frontera indicaria mal donde
        # termina cada grupo; se verifica celda por celda antes de embeberla.
        assert np.array_equal(membresia(XY, geometria), grupos),         f'la regla de centroide mas cercano no reproduce las etiquetas en el espacio {e}'

        GEOMETRIAS[str(e)] = geometria
        GRUPOS_POR_ESPACIO[str(e)] = grupos.tolist()

        # Vanos unicos de cada grupo: la union de los vanos de todas sus celdas. Un mismo vano
        # cuenta una sola vez aunque aparezca en varias ventanas del mismo grupo.
        asignado = CELDA_VANOS['celda'].map(_clave_celda)
        validas = asignado.notna()
        etiqueta_por_fila = pd.Series(grupos, index=range(len(CELDAS)))
        grupo_de_fila = asignado[validas].astype(int).map(etiqueta_por_fila)
        conteo = (CELDA_VANOS.loc[validas].assign(grupo=grupo_de_fila.values)
                  .groupby('grupo')['FID_VANO'].nunique()
                  .reindex(range(4)).fillna(0).astype(int).tolist())
        VANOS_POR_GRUPO[str(e)] = conteo

    _g0 = np.array(GRUPOS_POR_ESPACIO[str(IDX_ESPACIO_DEFECTO)])
    print(f'{len(CELDAS)} celdas con eventos | K-Means ajustado una vez')
    print('espacio fijo (eje x lineal, eje y logaritmico, minmax):')
    for g, nombre in enumerate(NOMBRES_GRUPOS):
        print(f'  {nombre:<11s} celdas: {int((_g0 == g).sum()):>4d}   '
              f'vanos unicos: {VANOS_POR_GRUPO[str(IDX_ESPACIO_DEFECTO)][g]:>6,}   '
              f'mediana UITI: {np.median(XY[_g0 == g, 1]):>12,.1f}')

    import geopandas as gpd
    import shapely
    # Misma geometria y mismo cruce que usa el mapa del reporte
    # (`chec_local_interpreter.plotting.plot_circuit_map_folium`): las lineas de MVLINSEC.shp se
    # cruzan por FID_VANO normalizado igual que `_norm_map_id`.


    # columns= limita la lectura a lo que se usa. El shapefile trae 44 columnas y aqui solo hacen
    # falta G3E_FID (el id del vano) y CIRCUITO; la geometria viene siempre. Leerlo completo
    # cuesta 0,75 s contra 0,08 s, sobre las mismas 60.053 filas.
    _lineas = gpd.read_file(REPO_ROOT / 'data' / 'GEO' / 'MVLINSEC.shp',
                            columns=['G3E_FID', 'CIRCUITO'])
    if str(_lineas.crs) != 'EPSG:4326':
        _lineas = _lineas.to_crs('EPSG:4326')
    _lineas['FID_VANO_GEO'] = _norm_id(_lineas['G3E_FID'])

    # El CSV ya se leyo y se normalizo en la celda de arranque: `df` trae estas mismas cuatro
    # columnas, con FECHA y UITI ya convertidos y FID_VANO pasado por el mismo _norm_id que se
    # aplica arriba a la geometria. Releerlo costaba otro segundo y, sobre todo, mantenia dos
    # copias que podian normalizarse distinto y romper el cruce vano <-> geometria sin dar error.
    _ev = df.rename(columns={'FID_VANO': 'FID_VANO_NORM'})

    _con_geo = set(_lineas['FID_VANO_GEO'].dropna())
    # TODOS los tramos del circuito, no solo los que registran eventos: el reporte dibuja los
    # demas en gris, y sin ellos el circuito aparece cortado.
    _circuitos_csv = set(_ev['CIRCUITO'].astype(str).unique())
    _utiles = _lineas[_lineas['CIRCUITO'].astype(str).isin(_circuitos_csv)]


    def _puntos_equipo(nombre_shp):
        ruta = REPO_ROOT / 'data' / 'GEO' / nombre_shp
        if not ruta.exists():
            return {}
        # Igual que con MVLINSEC: de las 57 columnas de transformadores y las 49 de switches
        # solo se usa CIRCUITO, y la geometria viaja aparte.
        _g = gpd.read_file(ruta, columns=['CIRCUITO'])
        if str(_g.crs) != 'EPSG:4326':
            _g = _g.to_crs('EPSG:4326')
        _g = _g[_g['CIRCUITO'].astype(str).isin(_circuitos_csv)]
        _g = _g[_g.geometry.notna() & ~_g.geometry.is_empty]
        # El redondeo se deja con el round() de Python a proposito. Vectorizarlo con np.round
        # ahorra 0,012 s de los 0,061 que cuesta este bloque, y a cambio mueve una coordenada:
        # -75.854105 es un empate exacto en el quinto decimal y cada libreria lo resuelve por un
        # camino distinto de punto flotante (-75.85411 contra -75.8541). Son 1,1 m en un
        # marcador, un cambio que no compensa doce milisegundos.
        salida = {}
        for _c, _grupo in _g.groupby(_g['CIRCUITO'].astype(str)):
            salida[_c] = {'lat': [round(float(p.y), 5) for p in _grupo.geometry],
                          'lon': [round(float(p.x), 5) for p in _grupo.geometry]}
        return salida


    TRAFOS_POR_CIRCUITO = _puntos_equipo('GDBCHEC_TRANSFOR.shp')
    SWITCHES_POR_CIRCUITO = _puntos_equipo('SWITCHES.shp')

    # Geometria por circuito: cada vano es un segmento de dos puntos, de modo que basta con sus
    # extremos. Va una sola vez y no depende de la ventana; lo unico que cambia es el color.
    # Las coordenadas salen de UNA pasada con shapely.get_coordinates, en vez de pedir `.xy`
    # geometria por geometria: sobre los 60.053 tramos eso baja de 0,51 s a 0,13 s. El redondeo
    # sigue siendo el round() de Python sobre la lista plana, no np.round: los dos resuelven de
    # forma distinta los empates exactos en el quinto decimal, y el resultado tiene que ser
    # identico al anterior valor por valor (verificado sobre los 228 circuitos).
    _partes, _idx_fila = shapely.get_parts(_utiles.geometry.values, return_index=True)
    _coords, _idx_parte = shapely.get_coordinates(_partes, return_index=True)
    _lon_planas = [round(v, 5) for v in _coords[:, 0].tolist()]
    _lat_planas = [round(v, 5) for v in _coords[:, 1].tolist()]
    _cortes_parte = np.searchsorted(_idx_parte, np.arange(len(_partes) + 1))
    _fids_parte = _utiles['FID_VANO_GEO'].to_numpy()[_idx_fila]
    _circ_parte = _utiles['CIRCUITO'].astype(str).to_numpy()[_idx_fila]

    GEO_POR_CIRCUITO = {}
    for _k in range(len(_partes)):
        _a, _b = _cortes_parte[_k], _cortes_parte[_k + 1]
        if _a == _b:                          # geometria vacia: no aporta ningun vertice
            continue
        _reg = GEO_POR_CIRCUITO.setdefault(_circ_parte[_k], {'fids': [], 'lat': [], 'lon': []})
        _reg['fids'].append(str(_fids_parte[_k]))
        _reg['lat'].append(_lat_planas[_a:_b])
        _reg['lon'].append(_lon_planas[_a:_b])
    for _info in GEO_POR_CIRCUITO.values():
        _info['centro'] = [round(float(np.mean([v for l in _info['lat'] for v in l])), 5),
                           round(float(np.mean([v for l in _info['lon'] for v in l])), 5)]

    # UITI acumulado por vano y ventana, solo para vanos con geometria.
    _ev_geo = _ev[_ev['FID_VANO_NORM'].isin(_con_geo)]
    # Por vano y ventana viajan las dos cifras juntas, [uiti, eventos], porque el tooltip las
    # muestra a la vez y enviarlas en dos diccionarios separados duplicaria las claves.
    UITI_VENTANA_VANO = []
    for _v in VENTANAS:
        _dentro = _ev_geo[(_ev_geo['FECHA'] >= _v['desde']) & (_ev_geo['FECHA'] < _v['hasta_excl'])]
        _agg = _dentro.groupby('FID_VANO_NORM')['UITI_VANO'].agg(['sum', 'count'])
        # iterrows() construye una Series de Python por fila: sobre las 110.759 celdas
        # vano x ventana eso costaba 1,0 s de los 8,9 que tardaba el cuaderno entero. Pasando el
        # redondeo y el casteo a numpy, columna completa de una vez, sale el mismo diccionario
        # en 0,03 s.
        _claves = _agg.index.astype(str).tolist()
        _sumas = np.round(_agg['sum'].to_numpy(), 3).tolist()
        _conteos = _agg['count'].to_numpy().astype(int).tolist()
        UITI_VENTANA_VANO.append({k: [s, c] for k, s, c in zip(_claves, _sumas, _conteos)})

    # Cortes de color UNICOS para todo el conjunto de datos. Antes eran cuantiles POR circuito:
    # cada mapa se autonormalizaba, de modo que el color mas alto de un circuito tranquilo podia
    # corresponder a menos UITI que el color mas bajo de uno critico, y dos mapas no se podian
    # comparar. Con cortes unicos, un color significa siempre el mismo UITI. Se calculan sobre
    # todas las celdas vano x ventana con UITI, y no por ventana, para que mover el slider
    # tampoco recoloree nada.
    _vals = [u[f][0] for u in UITI_VENTANA_VANO for f in u if u[f][0] > 0]
    UMBRALES_MAPA = [float(round(x, 4)) for x in
                     np.quantile(_vals, np.linspace(0, 1, len(CLASES_MAPA) + 1)[1:-1])]


    def _fmt_uiti(x):
        return f'{x:,.2f}' if abs(x) < 100 else f'{x:,.0f}'


    ROTULOS_MAPA = ([f'hasta {_fmt_uiti(UMBRALES_MAPA[0])}'] +
                    [f'{_fmt_uiti(a)} a {_fmt_uiti(b)}'
                     for a, b in zip(UMBRALES_MAPA, UMBRALES_MAPA[1:])] +
                    [f'mas de {_fmt_uiti(UMBRALES_MAPA[-1])}'])
    assert len(ROTULOS_MAPA) == len(CLASES_MAPA)
    print(f'cortes de color unicos sobre {len(_vals):,} celdas vano x ventana: ' +
          ' | '.join(f'{c} {r}' for c, r in zip(CLASES_MAPA, ROTULOS_MAPA)))

    # Extremos por circuito: con ellos el navegador ajusta el encuadre al tamano real del
    # circuito y al tamano real del mapa en pantalla, en vez de usar un zoom fijo.
    for _c, _i in GEO_POR_CIRCUITO.items():
        _la = [v for l in _i['lat'] for v in l]
        _lo = [v for l in _i['lon'] for v in l]
        _i['bounds'] = [round(min(_la), 5), round(max(_la), 5),
                        round(min(_lo), 5), round(max(_lo), 5)]

    _con_ev = sum(1 for v in GEO_POR_CIRCUITO.values() for f in v['fids']
                  if any(f in u for u in UITI_VENTANA_VANO))
    print(f'{len(GEO_POR_CIRCUITO)} circuitos con geometria | '
          f'{sum(len(v["fids"]) for v in GEO_POR_CIRCUITO.values()):,} tramos '
          f'({_con_ev:,} con eventos en alguna ventana, el resto en gris)')
    print(f'equipos: {sum(len(v["lat"]) for v in TRAFOS_POR_CIRCUITO.values()):,} transformadores | '
          f'{sum(len(v["lat"]) for v in SWITCHES_POR_CIRCUITO.values()):,} switches')
    _tot_csv = _ev['FID_VANO_NORM'].nunique()
    print(f'vanos del CSV con geometria: {len(set(_ev["FID_VANO_NORM"].dropna()) & _con_geo):,} '
          f'de {_tot_csv:,}')
    print(f'celdas (vano, ventana) con UITI: {sum(len(u) for u in UITI_VENTANA_VANO):,}')

    # 18 trazas fijas: 1 contorno de membresia, 4 del mapa (una por grupo), 1 trayectoria,
    # 2 del doble eje, 2 barras y 8 violines. El panel no crea ni destruye trazas, solo les
    # reescribe los datos.
    PERIODOS = [v['periodo'] for v in VENTANAS]
    # Rotulos sin el ano: el rango completo se lee igual y ocupa la mitad, que es lo que evita
    # que los ticks inclinados se metan en el titulo del panel de abajo. El periodo entero
    # sigue disponible en el hover via customdata.
    PERIODOS_CORTOS = [p.replace('2025-', '').replace('2026-', '') for p in PERIODOS]

    fig = make_subplots(
        # DOS filas. Las quince columnas existen solo para poder repartirlas con colspan: arriba
        # las dos vistas grandes, a media pantalla cada una; abajo la evolucion --que necesita
        # ancho para sus once fechas inclinadas-- y a su derecha los tres paneles de reparto.
        # Entre panel y panel se deja una columna EN BLANCO. Son los canales donde cada eje y
        # dibuja sus marcas, y donde el eje DERECHO de la evolucion pone las suyas y su rotulo
        # "Eventos". Sin ellos las etiquetas de un panel se superponian con el vecino.
        # El reparto es proporcional, no en pixeles: sobre un area util de 1480 px daba 98 px de
        # canal y 149 px por panel, y crece con la ventana del navegador.
        rows=2, cols=15,
        row_heights=[0.56, 0.44],
        column_widths=[1 / 15] * 15,
        vertical_spacing=0.12, horizontal_spacing=0.012,
        specs=[[{'colspan': 7}, None, None, None, None, None, None,
                None,
                {'type': 'map', 'colspan': 7}, None, None, None, None, None, None],
               [{'secondary_y': True, 'colspan': 6}, None, None, None, None, None,
                None,
                {'colspan': 2}, None,
                None,
                {'colspan': 2}, None,
                None,
                {'colspan': 2}, None]],
        # El orden es por filas sobre las celdas con spec: arriba agrupamiento y mapa, abajo
        # evolucion, barras y los dos violines. Los tres de abajo van cortos a proposito: en un
        # sexto del ancho un titulo largo se recorta, y ademas les entra el conteo de muestras.
        subplot_titles=('Agrupamiento circuito x ventana',
                        'Mapa del circuito -- UITI del vano en la ventana',
                        'Evolucion (color = grupo)',
                        'Muestras',
                        'UITI',
                        'Eventos'),
    )

    # Escala discreta de 4 escalones: cada banda del contorno toma el color de su grupo.
    ESCALA_CONTORNO = []
    for g, color in enumerate(COLORES_GRUPOS):
        ESCALA_CONTORNO.append([g / 4.0, color])
        ESCALA_CONTORNO.append([(g + 1) / 4.0, color])

    fig.add_trace(go.Contour(                                     # traza 0: membresia de fondo
        z=[[0, 0], [0, 0]], x=[0, 1], y=[0, 1],
        colorscale=ESCALA_CONTORNO, zmin=-0.5, zmax=3.5, showscale=False,
        opacity=0.28, hoverinfo='skip', line=dict(width=1.2, color='rgba(120,20,20,0.6)'),
        contours=dict(start=-0.5, end=3.5, size=1, coloring='fill'),
        name='Membresia', showlegend=False,
    ), row=1, col=1)
    for g in range(4):                                            # trazas 1-4: mapa por grupo
        fig.add_trace(go.Scattergl(
            x=[], y=[], mode='markers', name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
            marker=dict(size=5, color=COLORES_GRUPOS[g], opacity=OPACIDAD_FONDO),
            hovertext=[], hovertemplate='%{hovertext}<extra></extra>',
        ), row=1, col=1)
    fig.add_trace(go.Scatter(                                     # traza 5: trayectoria elegida
        x=[], y=[], mode='lines+markers+text', name='Trayectoria', showlegend=False,
        line=dict(color='rgba(120,20,20,0.55)', width=1.5),
        marker=dict(size=14, color=[], line=dict(width=1.6, color='rgb(40,10,12)')),
        textposition='top center', textfont=dict(size=9, color='rgb(90,15,20)'),
        hovertext=[], hovertemplate='%{hovertext}<extra></extra>',
    ), row=1, col=1)

    # Trazas 6-7: doble eje y. El UITI va contra el eje izquierdo y los eventos contra el
    # derecho, porque viven en escalas muy distintas y compartir eje aplastaria uno de los dos.
    # La linea identifica la VARIABLE, en azul y verde; el marcador identifica el GRUPO de esa
    # ventana, con la paleta del agrupamiento. Son dos codigos distintos sobre la misma serie,
    # y separarlos por canal -- trazo contra relleno del punto -- es lo que los hace legibles.
    # `customdata` viaja por punto como [periodo, grupo]: el grupo cambia ventana a ventana, y
    # el hover tiene que decir cual es sin obligar a cruzarlo con la nube.
    _CUSTOM_VACIO = [[p, 'sin eventos'] for p in PERIODOS]
    fig.add_trace(go.Scatter(
        x=PERIODOS_CORTOS, y=[None] * len(VENTANAS), mode='lines+markers', name='UITI acumulado',
        line=dict(color=COLOR_LINEA_UITI, width=2),
        marker=dict(size=[SERIE_TAM_UITI] * len(VENTANAS),
                    color=[COLOR_SIN_GRUPO] * len(VENTANAS),
                    line=dict(width=1.4, color='white')),
        customdata=_CUSTOM_VACIO,
        hovertemplate='%{customdata[0]}<br>Grupo: %{customdata[1]}'
                      '<br>UITI acumulado: %{y:,.1f}<extra></extra>',
    ), row=2, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(
        x=PERIODOS_CORTOS, y=[None] * len(VENTANAS), mode='lines+markers', name='Numero de eventos',
        line=dict(color=COLOR_LINEA_EVENTOS, width=2, dash='dot'),
        marker=dict(size=[SERIE_TAM_EVENTOS] * len(VENTANAS), symbol='square',
                    color=[COLOR_SIN_GRUPO] * len(VENTANAS),
                    line=dict(width=1.4, color='white')),
        customdata=_CUSTOM_VACIO,
        hovertemplate='%{customdata[0]}<br>Grupo: %{customdata[1]}'
                      '<br>Eventos: %{y:,}<extra></extra>',
    ), row=2, col=1, secondary_y=True)

    # El porcentaje va DENTRO de la barra y GIRADO -90 grados, o sea leyendose de abajo hacia
    # arriba: vertical ocupa el ancho de UN renglon en vez del de la cadena entera, que es lo
    # que lo hacia competir por el espacio en un panel de un sexto del ancho. `textangle` SOLO
    # existe en `Bar` -- `Scatter` no lo tiene -- asi que el porcentaje pasa a ser el `text` de
    # la barra y el conteo se muda a la traza de texto. `insidetextanchor='start'` lo ancla al
    # pie de la barra para que crezca hacia arriba desde la base, y `constraintext='none'`
    # evita que Plotly le encoja la letra hasta volverla ilegible: cuando no entra no se
    # achica, se va afuera, y de eso se encarga el umbral del panel.
    fig.add_trace(go.Bar(                                         # traza 8: muestras por grupo
        x=NOMBRES_GRUPOS, y=[0] * 4, text=[''] * 4,
        textposition='inside', textangle=-90, insidetextanchor='start',
        constraintext='none',
        # Sobre las dos barras oscuras un texto oscuro no se lee; los grupos van de claro a
        # oscuro, asi que el corte es fijo.
        insidetextfont=dict(size=11,
                            color=['rgb(40,10,12)', 'rgb(40,10,12)', 'white', 'white']),
        marker=dict(color=COLORES_GRUPOS, line=dict(width=0.5, color='rgba(60,10,10,0.6)')),
        showlegend=False, cliponaxis=False,
        hovertemplate='%{x}: %{y} muestras<extra></extra>',
    ), row=2, col=8)
    # El conteo queda AFUERA, arriba de la barra. Una traza de barras tiene un solo `text` y
    # ese ya lo ocupa el porcentaje, asi que hacen falta dos. Se agrega al final para no
    # correr indices.
    fig.add_trace(go.Scatter(
        x=NOMBRES_GRUPOS, y=[0] * 4, mode='text', text=[''] * 4,
        textposition='top center',
        textfont=dict(size=11, color='rgb(90,15,20)'),
        showlegend=False, hoverinfo='skip', cliponaxis=False,
    ), row=2, col=8)
    for fila, columna, etiqueta in [(2, 11, 'UITI acumulado'), (2, 14, 'Numero de eventos')]:  # trazas 10-17
        for g in range(4):
            fig.add_trace(go.Violin(
                x=[], y=[], name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
                showlegend=False, line=dict(color='rgba(90,15,20,0.85)', width=1),
                fillcolor=COLORES_GRUPOS[g], opacity=0.85,
                box_visible=True, meanline_visible=False, points=False, spanmode='hard',
                hovertemplate=f'%{{x}} -- {etiqueta}: %{{y:,.1f}}<extra></extra>',
            ), row=fila, col=columna)

    # Trazas 18-23 del mapa, agregadas AL FINAL a proposito: insertarlas antes correria los
    # indices de todo lo anterior. Una traza por clase de color mas una gris para los vanos sin
    # eventos en la ventana; Plotly no admite un color por segmento dentro de una misma traza.
    # La estructura va PRIMERO para quedar por DEBAJO del color: lleva todos los vanos del
    # circuito, tengan o no eventos en la ventana, y no se apaga nunca. Si se agregara despues,
    # su trazo fino se dibujaria encima del grueso y le partiria el color por la mitad.
    fig.add_trace(go.Scattermap(
        lat=[], lon=[], mode='lines', name='Estructura del circuito', showlegend=False,
        line=dict(width=ANCHO_SIN_EVENTOS, color=COLOR_SIN_EVENTO),
        hovertext=[], hoverinfo='text',
    ), row=1, col=9)
    for _c, (_clase, _color) in enumerate(zip(CLASES_MAPA, COLORES_MAPA)):
        fig.add_trace(go.Scattermap(
            lat=[], lon=[], mode='lines', name=_clase, showlegend=False,
            line=dict(width=ANCHO_MAPA, color=_color),
            hovertext=[], hoverinfo='text',
        ), row=1, col=9)
    for _nombre, _color, _tam in [('Transformadores', COLOR_TRAFO, TAM_TRAFO),
                                  ('Interruptores / switches', COLOR_SWITCH, TAM_SWITCH)]:
        fig.add_trace(go.Scattermap(
            lat=[], lon=[], mode='markers', name=_nombre, showlegend=False,
            marker=dict(size=_tam, color=_color),
            hovertext=[], hoverinfo='text',
        ), row=1, col=9)
    fig.update_layout(
        map=dict(style='carto-positron', center=dict(lat=5.07, lon=-75.52), zoom=10),
        title=dict(
            text='Trayectoria y agrupamiento de circuitos con ventana deslizante'
                 '<br><sup>Cada punto es un par circuito x ventana; K-Means (k=4) sobre el espacio '
                 'ajustado, grupos nombrados por la mediana del UITI</sup>',
            x=0.5, xanchor='center', yref='container', y=0.98, yanchor='top',
        ),
        legend=dict(title_text='', orientation='h', x=0.5, xanchor='center', y=1.015, yanchor='bottom'),
        # El titulo vive en el margen superior y la leyenda cuelga del borde del area de
        # dibujo. Con t=140 quedaban 63 px muertos entre el pie del titulo y la cima de la
        # leyenda, medidos en el navegador. Esta leyenda es FIJA -- los cuatro grupos y las
        # dos series del doble eje, siempre un renglon -- asi que el numero se puede clavar
        # aqui: con t=89 la leyenda arranca 12 px debajo del pie del titulo, sin traslape.
        margin=dict(t=89, r=90, b=60, l=90),
        # Sin `width`: la figura la fija el contenedor. Es la condicion para que
        # `default_width='100%'` y `config.responsive` de la celda siguiente surtan efecto y el
        # tablero use todo el ancho de la pantalla en el navegador.
        height=960, template='plotly_white', bargap=0.45, violingap=0.3,
    )
    fig.update_xaxes(title_text='Numero de eventos en la ventana', row=1, col=1)
    fig.update_yaxes(title_text='UITI acumulado en la ventana', row=1, col=1)
    # -55 grados y no -30: a 1.280 px el panel de la evolucion mide 396 px para once
    # ventanas, o sea 36 px por marca, y una etiqueta '11-01 a 11-30' de 65 px inclinada 30
    # grados ocupa 56 px de ancho. A 55 grados ocupa 37. Medido: a -30 se pisaban las once.
    fig.update_xaxes(tickangle=-55, tickfont=dict(size=9), row=2, col=1)
    # Los tres paneles de reparto y el eje DERECHO de la evolucion se reparten canales de
    # ~55 px -- eran 98 px cuando la figura ocupaba la pantalla entera. En ese hueco caben
    # las marcas de un panel, el rotulo 'Eventos' y las marcas del vecino solo si la letra
    # baja de la 12 por defecto a la 9, y si el rotulo se pega a sus propias marcas.
    for _col_reparto in (8, 11, 14):
        fig.update_yaxes(tickfont=dict(size=9), row=2, col=_col_reparto)
        fig.update_xaxes(tickfont=dict(size=9), row=2, col=_col_reparto)
    fig.update_yaxes(tickfont=dict(size=9), title_standoff=4,
                     row=2, col=1, secondary_y=True)
    fig.update_yaxes(tickfont=dict(size=9), row=2, col=1, secondary_y=False)
    # Y la fila de arriba, donde la marca '0' del eje x y la mas baja del eje y se tocaban
    # en la esquina: con letra 9 la etiqueta del eje y mide 22 px en vez de 30.
    fig.update_yaxes(tickfont=dict(size=9), row=1, col=1)
    fig.update_xaxes(tickfont=dict(size=9), row=1, col=1)
    # Los rotulos del eje x van sin el ano para que entren, asi que el salto de ano deja de
    # leerse. Una linea punteada entre la ultima ventana que arranca en un ano y la primera
    # que arranca en el siguiente lo vuelve explicito. El eje es categorico: las posiciones
    # son los indices, y la frontera entre la categoria k-1 y la k cae en k - 0.5.
    # Se ancla a mano en vez de usar add_vline(row=, col=): con un subplot de tipo `map` en la
    # misma figura, add_vline recorre todos los subplots y termina pasandole `xaxis` al
    # Scattermap, que no tiene esa propiedad.
    _ref_x_evo = 'x' + (fig.data[6].xaxis or 'x')[1:]
    _ref_y_evo = 'y' + (fig.data[6].yaxis or 'y')[1:] + ' domain'
    for _k in range(1, len(VENTANAS)):
        if VENTANAS[_k]['desde'].year != VENTANAS[_k - 1]['desde'].year:
            fig.add_shape(
                type='line', x0=_k - 0.5, x1=_k - 0.5, y0=0, y1=1,
                xref=_ref_x_evo, yref=_ref_y_evo,
                line=dict(dash='dot', width=1.5, color='rgba(60,60,60,0.75)'),
            )
            fig.add_annotation(
                # Adentro del panel, no arriba: en y=1 con anclaje inferior el rotulo se
                # montaba sobre el titulo del subplot y se leia "E2026ucion por ventana".
                x=_k - 0.5, y=0.97, xref=_ref_x_evo, yref=_ref_y_evo,
                text=str(VENTANAS[_k]['desde'].year), showarrow=False,
                xanchor='right', yanchor='top',
                font=dict(size=10, color='rgb(60,60,60)'),
            )
    fig.update_yaxes(title_text='UITI acumulado', row=2, col=1, secondary_y=False)
    fig.update_yaxes(title_text='Eventos', row=2, col=1, secondary_y=True, showgrid=False)
    # Sin title_text: el titulo del subplot ya nombra el panel y le suma el conteo, y el
    # rotulo del eje solo empujaba las marcas contra el panel vecino.
    fig.update_yaxes(rangemode='tozero', row=2, col=8)
    for _anotacion in fig.layout.annotations:
        _anotacion.font.size = 12

    # Los ids de eje se leen de las trazas ya construidas en vez de hardcodearse: al agregar
    # filas o un secondary_y la numeracion se corre, y un 'yaxis3' escrito a mano quedaria
    # apuntando al panel equivocado sin que nada falle a la vista.
    def _clave_eje(traza, cual):
        # OJO: `traza.y` son los DATOS; la referencia de eje vive en `traza.yaxis` ('y', 'y3'...).
        ref = getattr(traza, f'{cual}axis') or cual
        return f'{cual}axis' + ref[1:]


    # Los indices de traza se declaran una sola vez y viajan al JS. Antes estaban escritos a
    # mano en los dos lados, y al insertar el contorno adelante se habrian corrido todos sin
    # que nada fallara a la vista: el panel escribiria en la traza equivocada.
    IDX = {
        'contorno': 0,
        'mapa': [1, 2, 3, 4],
        'trayectoria': 5,
        'serieUiti': 6,
        'serieEventos': 7,
        'barrasMuestras': 8,
        'conteoMuestras': 9,
        'violinUiti': [10, 11, 12, 13],
        'violinEventos': [14, 15, 16, 17],
        'mapaSinEventos': 18,
        'mapaClases': [19 + k for k in range(len(CLASES_MAPA))],
        'mapaTrafos': 19 + len(CLASES_MAPA),
        'mapaSwitches': 20 + len(CLASES_MAPA),
    }
    assert len(fig.data) == 21 + len(CLASES_MAPA), len(fig.data)
    # `marker.size` de las dos series tiene que ser un ARRAY: es lo que permite agrandar el
    # punto de la ventana vigente sin partir la serie en dos trazas.
    assert all(isinstance(fig.data[i].marker.size, (list, tuple))
               for i in (IDX['serieUiti'], IDX['serieEventos'])), (
        'marker.size debe ser un array: el punto de la ventana vigente va al triple')
    assert all(len(fig.data[i].marker.size) == len(VENTANAS)
               for i in (IDX['serieUiti'], IDX['serieEventos']))
    assert fig.data[IDX['conteoMuestras']].mode == 'text'
    assert fig.data[IDX['barrasMuestras']].textangle == -90
    # El mapa comparte la paleta con la nube; si alguien cambia una sola, esto falla al generar.
    assert ([fig.data[i].marker.color for i in IDX['mapa']] ==
            [fig.data[i].line.color for i in IDX['mapaClases']] == COLORES_GRUPOS)
    assert all(fig.data[i].type == 'scattermap'
               for i in IDX['mapaClases'] + [IDX['mapaSinEventos'],
                                             IDX['mapaTrafos'], IDX['mapaSwitches']])
    assert fig.data[IDX['contorno']].type == 'contour'
    assert all(fig.data[i].type == 'scattergl' for i in IDX['mapa'])
    assert all(fig.data[i].type == 'violin' for i in IDX['violinUiti'] + IDX['violinEventos'])
    assert fig.data[IDX['barrasMuestras']].type == 'bar'
    # El gris de los sin eventos, con los mismos valores que 04.
    assert (fig.data[IDX['mapaSinEventos']].line.width == ANCHO_SIN_EVENTOS
            and fig.data[IDX['mapaSinEventos']].line.color == COLOR_SIN_EVENTO)
    assert all(fig.data[i].line.width == ANCHO_MAPA == 7.0 for i in IDX['mapaClases'])
    # Los equipos, con el tamano de 01: el mapa de 03 y el de 01 tienen que dibujar el mismo
    # transformador del mismo tamano.
    assert (fig.data[IDX['mapaTrafos']].marker.size,
            fig.data[IDX['mapaSwitches']].marker.size) == (TAM_TRAFO, TAM_SWITCH) == (14, 12)

    # Titulos que el panel reescribe con el numero de muestras. El indice se resuelve por TEXTO
    # aqui y no a mano: si alguien reordena los subplots, el indice sigue siendo el correcto, y si
    # alguien cambia el texto esto falla al generar en vez de reescribir el titulo equivocado.
    TITULOS_N = {}
    for _clave, _texto in [('barras', 'Muestras'),
                           ('violinU', 'UITI'),
                           ('violinN', 'Eventos')]:
        _pos = [i for i, _a in enumerate(fig.layout.annotations) if _a.text == _texto]
        assert len(_pos) == 1, (_texto, _pos)
        TITULOS_N[_clave] = [_pos[0], _texto]

    EJES = {
        'mapaX': _clave_eje(fig.data[IDX['mapa'][0]], 'x'),
        'mapaY': _clave_eje(fig.data[IDX['mapa'][0]], 'y'),
        'barrasMuestras': _clave_eje(fig.data[IDX['barrasMuestras']], 'y'),
        'violinUiti': _clave_eje(fig.data[IDX['violinUiti'][0]], 'y'),
        'violinEventos': _clave_eje(fig.data[IDX['violinEventos'][0]], 'y'),
    }

    # El print cierra la celda a proposito: si terminara en un update_*(), Jupyter mostraria
    # la Figure devuelta y quedarian dos figuras, una de ellas sin panel de control.
    print(f'{len(fig.data)} trazas: 1 contorno + 4 nube + 1 trayectoria + 2 doble eje '
          f'+ 1 barra + 1 pct + 8 violines + {len(CLASES_MAPA) + 3} mapa')
    print('ejes resueltos:', EJES)

    DIV_FIGURA = 'trayectorias-circuitos'

    CONTEXTO = {
        'div': DIV_FIGURA,
        'circuitos': CIRCUITOS,
        'ventanas': [{'etiqueta': v['etiqueta'], 'periodo': v['periodo']} for v in VENTANAS],
        'porCircuito': POR_CIRCUITO,
        'espacios': [[bool(lx), bool(ly), prep] for lx, ly, prep in ESPACIOS],
        'grupos': NOMBRES_GRUPOS,
        'colores': COLORES_GRUPOS,
        'colorSinGrupo': COLOR_SIN_GRUPO,
        'gruposPorEspacio': GRUPOS_POR_ESPACIO,
        'vanosPorGrupo': VANOS_POR_GRUPO,
        'sinSeleccion': SIN_SELECCION,
        'ejes': EJES,
        'titulos': TITULOS_N,
        'idx': IDX,
        'geometrias': GEOMETRIAS,
        'extension': EXTENSION,
        'resolucion': 90,
        'opacidadFoco': OPACIDAD_FOCO,
        'opacidadFondo': OPACIDAD_FONDO,
        'serieTamUiti': SERIE_TAM_UITI,
        'serieTamEventos': SERIE_TAM_EVENTOS,
        'factorPuntoActivo': FACTOR_PUNTO_ACTIVO,
        'geo': GEO_POR_CIRCUITO,
        'uitiVentana': UITI_VENTANA_VANO,
        'umbrales': UMBRALES_MAPA,
        'clases': CLASES_MAPA,
        'trafos': TRAFOS_POR_CIRCUITO,
        'switches': SWITCHES_POR_CIRCUITO,
    }

    _opciones = ''.join(
        f'<option value="{c}"{" selected" if i == 0 else ""}>{c}</option>'
        for i, c in enumerate(CIRCUITOS))
    # Barra de color del mapa. Los cortes son unicos para todo el dataset, asi que los rotulos
    # se imprimen una sola vez aqui en vez de reescribirse en el navegador por circuito.
    _escala_html = '<span style="display:inline-flex;gap:2px;align-items:center;">' + ''.join(
        f'<span style="display:inline-block;width:20px;height:10px;background:{c};"></span>'
        f'<span style="font-size:10px;color:#7a5c58;margin-right:8px;">{n} ({r})</span>'
        for n, c, r in zip(CLASES_MAPA, COLORES_MAPA, ROTULOS_MAPA)) + '</span>'

    PANEL_HTML = f'''
<style>
  .panel-tray {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 13px;
    display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-end;
    /* El panel sigue el ancho de la figura, que ya no es fijo: la figura se genera sin
       `width` y con `default_width='100%'`, de modo que ocupa el ancho disponible.
       `border-box` mantiene relleno y bordes DENTRO de ese ancho y no encima. */
    width: 100%; box-sizing: border-box;
    margin: 0 0 6px 0; padding: 12px 14px;
    border: 1px solid #e4c4c0; border-left: 4px solid rgb(203,24,29);
    border-radius: 6px; background: #fdf7f6; color: #2b2b2b;
  }}
  .panel-tray label {{ display: block; font-weight: 600; margin-bottom: 4px; }}
  .panel-tray select {{
    font: inherit; padding: 4px 6px; border: 1px solid #c9a9a5;
    border-radius: 4px; background: #fff; color: #2b2b2b; min-width: 140px;
  }}
  .panel-tray .chk {{ font-weight: 600; display: flex; align-items: center; gap: 6px; }}
  .panel-tray .chk input {{ margin: 0; }}
  .panel-tray .grupo-chk {{ display: flex; flex-direction: column; gap: 6px; }}
  .panel-tray button {{
    font: inherit; font-weight: 600; padding: 6px 12px; cursor: pointer;
    border: 1px solid rgb(203,24,29); border-radius: 4px;
    background: rgb(203,24,29); color: #fff;
  }}
  .panel-tray button:hover {{ background: rgb(165,15,21); }}
  .panel-aviso {{
    flex-basis: 100%; font-size: 12px; color: #7a5c58; margin: 0; font-weight: 400;
  }}
</style>
<div class="panel-tray">
  <div><label for="tr-circuito">Circuito</label>
       <select id="tr-circuito">
         <option value="{SIN_SELECCION}">{SIN_SELECCION}</option>{_opciones}
       </select></div>
  <div style="flex-basis:100%; display:flex; align-items:center; gap:10px;">
    <label for="tr-ventana" style="margin:0; white-space:nowrap;">Ventana</label>
    <input type="range" id="tr-ventana" min="0" max="{len(VENTANAS) - 1}" value="0" step="1"
           style="flex:1; accent-color: rgb(203,24,29);">
    <span id="tr-ventana-txt" style="font-weight:600; white-space:nowrap; min-width:190px;"></span>
  </div>
  <div style="flex-basis:100%; font-size:11.5px; display:flex; flex-wrap:wrap;
              gap:4px 14px; align-items:center; color:#5b4a48;">
    <span style="font-weight:600;">Mapa:</span>
    <span>UITI del vano en la ventana, con cortes fijos para todos los circuitos</span>
    {_escala_html}
    <span><span style="display:inline-block;width:20px;height:0;border-top:3px solid
      {COLOR_SIN_EVENTO};vertical-align:middle;margin-right:5px;"></span>Sin eventos</span>
    <span><span style="display:inline-block;width:18px;height:18px;background:{COLOR_TRAFO};
      border-radius:50%;margin-right:5px;"></span>Transformador</span>
    <span><span style="display:inline-block;width:18px;height:18px;background:{COLOR_SWITCH};
      border-radius:50%;margin-right:5px;"></span>Interruptor</span>
  </div>
  <div style="flex-basis:100%; display:flex; align-items:center; gap:10px;
              margin:2px 0 6px 0;">
    <button type="button" id="tr-centrar"
      title="Encuadra el mapa sobre los vanos que registraron eventos en el periodo elegido. El encuadre automatico usa el circuito completo, que en un circuito largo deja los vanos con eventos apretados en una esquina.">Centrar en vanos con eventos</button>
  </div>
  <p class="panel-aviso" id="tr-aviso"></p>
</div>
'''

    PANEL_JS = '''
<script type="text/javascript">
(function () {
  var CTX = %s;
  var d = document;

  // Mismo recorrido canonico que CELDAS en Python: circuito y despues ventana, saltando
  // las celdas sin eventos. De aqui sale el indice con que se leen las etiquetas de grupo.
  var CELDAS = [];
  CTX.circuitos.forEach(function (c, ci) {
    var reg = CTX.porCircuito[c];
    CTX.ventanas.forEach(function (v, vi) {
      if (reg.n[vi] > 0) { CELDAS.push([ci, vi]); }
    });
  });

  function etiquetaPunto(ci, vi, grupo) {
    var v = CTX.ventanas[vi], reg = CTX.porCircuito[CTX.circuitos[ci]];
    return '<b>' + CTX.circuitos[ci] + '</b> -- ' + v.etiqueta +
           '<br>' + v.periodo +
           '<br>Grupo: <b>' + CTX.grupos[grupo] + '</b>' +
           '<br>Eventos: ' + reg.n[vi] +
           '<br>UITI acumulado: ' + reg.u[vi];
  }

  function ejeGrilla(min, max, n, log) {
    // En logaritmica la grilla se reparte geometricamente, para que quede pareja en pantalla.
    var out = [], lo = log ? Math.log10(min) : min, hi = log ? Math.log10(max) : max;
    var paso = (hi - lo) / (n - 1);
    for (var i = 0; i < n; i++) {
      var v = lo + i * paso;
      out.push(log ? Math.pow(10, v) : v);
    }
    return out;
  }

  function contorno(geo) {
    // Membresia por centroide mas cercano en el espacio ajustado: la misma regla que
    // scikit-learn usa en predict(), verificada contra sus etiquetas del lado de Python.
    var ext = CTX.extension, n = CTX.resolucion;
    var lx = geo.logs[0], ly = geo.logs[1];
    var gx = ejeGrilla(ext[0], ext[1], n, lx);
    var gy = ejeGrilla(ext[2], ext[3], n, ly);
    var cen = geo.centroides, off = geo.offset, esc = geo.scale;
    var z = [];
    for (var j = 0; j < n; j++) {
      var ty = ((ly ? Math.log10(gy[j]) : gy[j]) - off[1]) / esc[1];
      var fila = [];
      for (var i = 0; i < n; i++) {
        var tx = ((lx ? Math.log10(gx[i]) : gx[i]) - off[0]) / esc[0];
        var mejor = 0, dmin = Infinity;
        for (var c = 0; c < cen.length; c++) {
          var a = tx - cen[c][0], b = ty - cen[c][1], dd = a * a + b * b;
          if (dd < dmin) { dmin = dd; mejor = c; }
        }
        fila.push(mejor);
      }
      z.push(fila);
    }
    return {z: z, x: gx, y: gy};
  }

  var ULTIMO_CENTRADO = null;   // circuito sobre el que ya se encuadro el mapa

  function claseDe(valor, umbrales) {
    if (!(valor > 0)) { return -1; }              // sin eventos en esta ventana
    for (var i = 0; i < umbrales.length; i++) {
      if (valor <= umbrales[i]) { return i; }
    }
    return umbrales.length;
  }

  function ventanaActual() {
    var el = d.getElementById('tr-ventana');
    return el ? (parseInt(el.value, 10) || 0) : 0;
  }

  function limEje(lo, hi, log) {
    // En log Plotly espera el rango YA en log10; el piso evita un log10(0) si la
    // extension arranca en cero.
    return log ? [Math.log10(Math.max(lo, 1e-6) * 0.85), Math.log10(hi * 1.15)]
               : [0, hi * 1.05];
  }

  // --- Vertices para el hover del vano --------------------------------------------
  // El hover de una traza de lineas en Scattermap NO se resuelve contra la linea: se
  // resuelve contra sus VERTICES. plotly.js mide la distancia del cursor a cada punto
  // con radio max(3, marker.mrc) y descarta lo que quede a mas de `hoverdistance`
  // (20 px por defecto), asi que una linea sin vertices cerca del cursor NO tiene
  // etiqueta -- por mas ancha que sea, el ancho de linea no participa del calculo.
  // Los tramos de MVLINSEC.shp traen EXACTAMENTE 2 vertices (60.053 de 60.053 medidos),
  // uno en cada extremo: en un vano largo (p90 = 388 m, maximo 12 km) el centro de la
  // linea quedaba a mas de 20 px de los dos extremos y no mostraba ningun codigo.
  // Se interpolan vertices cada ~25 m para que cualquier punto del vano tenga uno a
  // menos de ~13 m. Corre en el navegador y solo sobre el circuito ACTIVO, asi que el
  // JSON del panel no crece ni un byte.
  var PASO_VERTICE = 0.00022;      // grados ~= 25 m a esta latitud
  var MAX_CORTES_TRAMO = 600;      // techo para el vano de 12 km
  var MARCA_VANO = 0.00013;        // grados de longitud ~= 14 m a cada lado del extremo
  var GEO_DENSO = {};              // cache por circuito: densificar una vez, no por ventana

  function densificar(la, lo) {
    if (!la || la.length < 2) { return [la || [], lo || []]; }
    var oLa = [la[0]], oLo = [lo[0]], i, j, n, dLa, dLo;
    for (i = 1; i < la.length; i++) {
      dLa = la[i] - la[i - 1];
      dLo = lo[i] - lo[i - 1];
      n = Math.ceil(Math.max(Math.abs(dLa), Math.abs(dLo)) / PASO_VERTICE);
      n = Math.max(1, Math.min(MAX_CORTES_TRAMO, n));
      for (j = 1; j < n; j++) {
        oLa.push(la[i - 1] + dLa * j / n);
        oLo.push(lo[i - 1] + dLo * j / n);
      }
      oLa.push(la[i]);
      oLo.push(lo[i]);
    }
    return [oLa, oLo];
  }

  function geoDenso(circ, info) {
    if (GEO_DENSO[circ]) { return GEO_DENSO[circ]; }
    var la = [], lo = [], i, den;
    for (i = 0; i < info.fids.length; i++) {
      den = densificar(info.lat[i], info.lon[i]);
      la.push(den[0]);
      lo.push(den[1]);
    }
    GEO_DENSO[circ] = {lat: la, lon: lo};
    return GEO_DENSO[circ];
  }

  // --- Encuadre del mapa ------------------------------------------------------------
  // fitBounds real en Web Mercator, no un zoom derivado del span en grados. Un grado de
  // latitud y uno de longitud no ocupan los mismos pixeles, y el mapa ya no tiene ancho
  // fijo: al ocupar todo el ancho de la pantalla, la formula en grados dejaba el circuito
  // centrado pero recortado arriba y abajo. El zoom lo fija la dimension que se queda sin
  // lugar primero, medida sobre el tamano real del lienzo.
  var TESELA_PX = 512;            // tamano de tesela con que proyecta MapLibre
  var MARGEN_ENCUADRE = 0.9;      // deja borde para que los vanos extremos no toquen el filo

  function mercatorY(lat) {
    var r = lat * Math.PI / 180;
    return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2;
  }

  function tamanoMapa(gd) {
    // El lienzo de MapLibre da la medida exacta. Si todavia no existe se cae al dominio del
    // subplot sobre el area de dibujo, que es la misma cuenta que hace Plotly.
    var lienzo = gd.querySelector('.maplibregl-map');
    if (lienzo) {
      var caja = lienzo.getBoundingClientRect();
      if (caja.width > 0 && caja.height > 0) { return [caja.width, caja.height]; }
    }
    var fl = gd._fullLayout;
    if (!fl || !fl._size || !fl.map || !fl.map.domain) { return [0, 0]; }
    var dom = fl.map.domain;
    return [(dom.x[1] - dom.x[0]) * fl._size.w, (dom.y[1] - dom.y[0]) * fl._size.h];
  }

  function encuadre(b, ancho, alto) {
    var restricciones = [];
    if (ancho > 0) {
      restricciones.push(ancho * MARGEN_ENCUADRE /
                         (TESELA_PX * Math.max(Math.abs(b[3] - b[2]) / 360, 1e-12)));
    }
    if (alto > 0) {
      restricciones.push(alto * MARGEN_ENCUADRE /
                         (TESELA_PX * Math.max(Math.abs(mercatorY(b[0]) - mercatorY(b[1])),
                                               1e-12)));
    }
    if (!restricciones.length) { return null; }
    // Sin techo, un circuito de un solo vano pediria un zoom sin fin; sin piso, uno que
    // cruza el departamento se saldria de la region.
    // El techo es 17 y no 15. Medido sobre los 208 circuitos, el encuadre mas cerrado que
    // pide alguno es 16,9, de modo que 17 solo cubre el caso degenerado -- una extension
    // nula -- y nunca recorta un encuadre real. Con 15 saturaba el 2%% de los circuitos a 2560 px, y saturar el techo es
    // volver al zoom fijo que este bloque vino a sustituir, justo en los circuitos
    // pequenos, que son los que mas necesitan acercarse.
    var escala = Math.min.apply(null, restricciones);
    return {center: {lat: (b[0] + b[1]) / 2, lon: (b[2] + b[3]) / 2},
            zoom: Math.min(17, Math.max(3, Math.log(escala) / Math.LN2))};
  }

  function encuadrarCircuito(gd, circuito) {
    var info = (circuito !== CTX.sinSeleccion) ? CTX.geo[circuito] : null;
    if (!info || !info.bounds) { return; }
    var tam = tamanoMapa(gd);
    var vista = encuadre(info.bounds, tam[0], tam[1]);
    if (!vista) { return; }
    Plotly.relayout(gd, {'map.center': vista.center, 'map.zoom': vista.zoom});
  }

  // --- Encuadre sobre los vanos CON EVENTOS -------------------------------------------
  // El encuadre automatico mira el circuito ENTERO, que es lo correcto al cambiar de
  // circuito. Pero lo que se estudia son los vanos que registraron eventos, y en un
  // circuito largo esos pueden caer todos en una esquina: el mapa queda tecnicamente
  // bien encuadrado y practicamente inservible. Este boton encuadra sobre ellos.
  //
  // Los limites salen de las trazas que el mapa ACABA de dibujar, no de un calculo
  // paralelo sobre CTX: asi no pueden discrepar de lo que se ve en pantalla, y siguen
  // sin codigo extra a lo que el panel este filtrando en ese momento.
  function boundsDeTrazas(gd, indices) {
    var laMin = Infinity, laMax = -Infinity, loMin = Infinity, loMax = -Infinity;
    var hay = false, i, k, t, la, lo;
    for (i = 0; i < indices.length; i++) {
      t = gd.data[indices[i]];
      if (!t || !t.lat) { continue; }
      for (k = 0; k < t.lat.length; k++) {
        la = t.lat[k]; lo = t.lon[k];
        // Los tramos viajan separados por null. Comparar un null como numero lo trata
        // como cero y arrastraria el encuadre al golfo de Guinea.
        if (la === null || lo === null || la === undefined || lo === undefined) { continue; }
        hay = true;
        if (la < laMin) { laMin = la; }
        if (la > laMax) { laMax = la; }
        if (lo < loMin) { loMin = lo; }
        if (lo > loMax) { loMax = lo; }
      }
    }
    return hay ? [laMin, laMax, loMin, loMax] : null;
  }

  function encuadrarEventos(gd) {
    var b = boundsDeTrazas(gd, CTX.idx.mapaClases);
    if (!b) {
      // Sin un solo vano con eventos no hay nada que encuadrar. Se cae al circuito
      // completo y se DICE: un boton que no produce ningun cambio visible se lee como
      // roto, y aqui el mapa ya estaba encuadrado en el circuito.
      var aviso = d.getElementById('tr-aviso');
      if (aviso) {
        aviso.textContent = 'Ningun vano registro eventos en este periodo: el mapa se '
                          + 'encuadra sobre el circuito completo.';
      }
      encuadrarCircuito(gd, d.getElementById('tr-circuito').value);
      return;
    }
    var tam = tamanoMapa(gd);
    var vista = encuadre(b, tam[0], tam[1]);
    if (!vista) { return; }
    Plotly.relayout(gd, {'map.center': vista.center, 'map.zoom': vista.zoom});
  }

  (function () {
    var boton = d.getElementById('tr-centrar');
    if (!boton) { return; }
    boton.addEventListener('click', function () {
      var gd = d.getElementById(CTX.div);
      if (gd && gd._fullLayout) { encuadrarEventos(gd); }
    });
  })();

  // `forzar` existe por MapLibre: los redibujados de arranque repiten esta llamada
  // con los mismos argumentos justamente porque el primero se pudo perder mientras
  // el subplot de mapa todavia no estaba montado. Sin esa puerta, la firma los
  // cortaria y el mapa se quedaria vacio.
  function dibujarMapa(gd, circuito, forzar) {
    var w = ventanaActual();
    var v = CTX.ventanas[w];
    d.getElementById('tr-ventana-txt').textContent = v.etiqueta + ': ' + v.periodo;

    // De lo unico que depende este dibujo: que ventana y que circuito.
    var firma = w + '|' + circuito;
    if (!forzar && firma === FIRMA_MAPA) { return; }
    FIRMA_MAPA = firma;

    // La estructura del circuito se dibuja SIEMPRE completa y en negro: todos sus vanos,
    // tengan o no eventos en la ventana. Encima, y solo encima, va el trazo grueso de color
    // de los que si tuvieron. Asi el circuito nunca desaparece al mover el slider -- lo que
    // cambia es cuanto de el queda pintado, no cuanto de el existe.
    var nClases = CTX.clases.length;
    var lat = [], lon = [], txt = [], i;
    var elat = [], elon = [], etxt = [];
    for (i = 0; i < nClases; i++) { lat.push([]); lon.push([]); txt.push([]); }

    var info = (circuito !== CTX.sinSeleccion) ? CTX.geo[circuito] : null;
    if (info) {
      var denso = geoDenso(circuito, info);
      // Los umbrales son unicos para todo el dataset, no del circuito: por eso dos mapas
      // se pueden comparar entre si y con los grupos del agrupamiento.
      var uiti = CTX.uitiVentana[w], umbrales = CTX.umbrales;
      for (i = 0; i < info.fids.length; i++) {
        var fid = info.fids[i], dato = uiti[fid];
        var valor = dato ? dato[0] : 0, eventos = dato ? dato[1] : 0;
        var c = claseDe(valor, umbrales);
        var etiqueta = '<b>Vano ' + fid + '</b><br>' + v.etiqueta + ': ' + v.periodo +
                       '<br>UITI acumulado: ' + (dato ? valor.toLocaleString() : '0') +
                       '<br>Eventos: ' + eventos;
        // Un null entre segmentos corta la linea: sin eso Plotly une el final de un vano
        // con el principio del siguiente y el mapa se llena de tramos que no existen.
        // El texto se repite por punto porque el hover se resuelve punto a punto.
        // La etiqueta se repite en CADA vertice densificado: el hover engancha en el
        // punto mas cercano, y todos los del vano dicen lo mismo.
        var k, dLa = denso.lat[i], dLo = denso.lon[i];
        elat = elat.concat(dLa, [null]);
        elon = elon.concat(dLo, [null]);
        for (k = 0; k < dLa.length; k++) { etxt.push(etiqueta); }
        etxt.push('');
  // --- Marca de inicio y fin de vano ------------------------------------------------
  // Un guion HORIZONTAL negro sobre cada extremo del vano, para TODOS los vanos, tengan
  // o no eventos. No se puede hacer con un simbolo de marcador: `marker.symbol` de
  // Scattermap solo acepta iconos del sprite del estilo del mapa (lista maki), ahi no hay
  // ningun simbolo de linea horizontal, y usando un simbolo distinto de 'circle' se
  // pierden color y tamaño por punto. Asi que el guion se dibuja como un SEGMENTO mas
  // dentro de la MISMA traza negra de estructura: hereda su color y su ancho, no agrega
  // ninguna traza, y sirve tambien como punto de hover del vano.
        var oLa = info.lat[i], oLo = info.lon[i], ex, ie;
        for (ex = 0; ex < 2; ex++) {
          ie = ex === 0 ? 0 : oLa.length - 1;
          elat = elat.concat([oLa[ie], oLa[ie]], [null]);
          elon = elon.concat([oLo[ie] - MARCA_VANO, oLo[ie] + MARCA_VANO], [null]);
          etxt.push(etiqueta); etxt.push(etiqueta); etxt.push('');
        }
        // Sin eventos en la ventana no hay clase, y por lo tanto no hay trazo grueso: el
        // vano queda dibujado, pero solo en negro.
        if (c >= 0) {
          lat[c] = lat[c].concat(dLa, [null]);
          lon[c] = lon[c].concat(dLo, [null]);
          for (k = 0; k < dLa.length; k++) { txt[c].push(etiqueta); }
          txt[c].push('');
        }
      }
    }
    // Equipos: no dependen de la ventana, solo del circuito, pero se reescriben igual
    // porque cambiar de circuito tiene que vaciarlos.
    var tr = (info && CTX.trafos[circuito]) || {lat: [], lon: []};
    var sw = (info && CTX.switches[circuito]) || {lat: [], lon: []};
    var trTxt = tr.lat.map(function () { return '<b>Transformador</b><br>Circuito: ' + circuito; });
    var swTxt = sw.lat.map(function () { return '<b>Interruptor / switch</b><br>Circuito: ' + circuito; });
    // Las trazas del mapa se escriben en UNA llamada, equipos incluidos. Eran dos
    // restyle seguidos, de 36 y 21 ms medidos, y el costo lo fija la llamada -- que
    // redibuja la figura entera -- no cuantas trazas lleve dentro.
    var indices = [CTX.idx.mapaSinEventos].concat(
      CTX.idx.mapaClases, [CTX.idx.mapaTrafos, CTX.idx.mapaSwitches]);
    Plotly.restyle(gd, {
      lat: [elat].concat(lat, [tr.lat, sw.lat]),
      lon: [elon].concat(lon, [tr.lon, sw.lon]),
      hovertext: [etxt].concat(txt, [trTxt, swTxt]),
    }, indices);

    // La barra de color ya no se reescribe por circuito: los cortes son unicos, de modo
    // que sus rotulos se imprimen una sola vez en el panel. Una barra de color de Plotly
    // colgada de una traza no se dibuja sobre un subplot de mapa, por eso vive en el HTML.
    // Recentrar SOLO al cambiar de circuito. Si el usuario se acerco a una zona y mueve el
    // slider, volver a encuadrar descartaria el zoom que eligio; la ventana repinta
    // colores, no cambia de circuito.
    if (info && info.bounds && circuito !== ULTIMO_CENTRADO) {
      ULTIMO_CENTRADO = circuito;
      encuadrarCircuito(gd, circuito);
    }
  }

  // Grupos del espacio vigente, para que el slider rehaga el reparto sin recalcular
  // el espacio.
  var ETIQUETAS_VIGENTES = null;

  // Lo ultimo que dibujo el mapa. Un arrastre que vuelve a la ventana en que empezo,
  // o un `aplicar()` que llega detras del manejador del deslizador, pedian el mismo
  // dibujo otra vez: cada `restyle` que cambia algo cuesta un redibujado completo de
  // la figura, asi que la repeticion se paga entera.
  var FIRMA_MAPA = null;

  // Barras y violines describen SOLO la ventana elegida: son la foto del reparto en ese
  // periodo, no el acumulado de las 11 ventanas. La nube de fondo si las lleva todas, asi
  // que el reparto es un corte de lo dibujado, no su resumen. Devuelve el conteo maximo
  // sobre TODAS las ventanas, que es lo que fija el techo del eje de barras.
  // Los titulos de las barras y de los violines dicen cuantas muestras resumen. Sin eso, dos
  // ventanas con reparto parecido se leen igual aunque una tenga la mitad de circuitos.
  // Se reescriben en UNA sola llamada y por indice, para no pisar las flechas, que viven en
  // el mismo array de anotaciones.
  function ponerTitulos(gd, sufijo) {
    var cambios = {}, claves = ['barras', 'violinU', 'violinN'];
    for (var i = 0; i < claves.length; i++) {
      var par = CTX.titulos[claves[i]], pos = par[0], texto = par[1] + sufijo;
      // El snapshot guarda las MISMAS referencias que gd.layout.annotations, asi que
      // actualizarlo evita que el relayout completo de aplicar() revierta el titulo.
      if (fig_anotaciones && fig_anotaciones[pos]) { fig_anotaciones[pos].text = texto; }
      cambios['annotations[' + pos + '].text'] = texto;
    }
    Plotly.relayout(gd, cambios);
  }

  function dibujarReparto(gd, etiquetas) {
    var w = ventanaActual(), i, g;
    var vg = [[], [], [], []], vu = [[], [], [], []], vn = [[], [], [], []];
    var porVentana = [];
    for (i = 0; i < CTX.ventanas.length; i++) { porVentana.push([0, 0, 0, 0]); }
    for (var k = 0; k < CELDAS.length; k++) {
      var ci = CELDAS[k][0], vi = CELDAS[k][1];
      g = etiquetas[k];
      porVentana[vi][g] += 1;
      if (vi !== w) { continue; }
      var reg = CTX.porCircuito[CTX.circuitos[ci]];
      vg[g].push(CTX.grupos[g]); vu[g].push(reg.u[vi]); vn[g].push(reg.n[vi]);
    }
    var muestras = porVentana[w] || [0, 0, 0, 0], maxGlobal = 1;
    for (i = 0; i < porVentana.length; i++) {
      for (g = 0; g < 4; g++) {
        if (porVentana[i][g] > maxGlobal) { maxGlobal = porVentana[i][g]; }
      }
    }

    // El porcentaje se calcula sobre las celdas de ESTA ventana, para que las cuatro
    // cifras sumen 100. Dentro de la barra solo si hay altura; si no, pegado al conteo de
    // afuera, o el texto de media altura caeria sobre el eje encimandose con el nombre del
    // grupo. Atencion: este bloque se arma con formateo de cadena, de modo que un
    // simbolo de porcentaje suelto produce "not enough arguments for format string".
    var totalM = muestras[0] + muestras[1] + muestras[2] + muestras[3];
    var pctM = muestras.map(function (c) {
      return totalM ? (100 * c / totalM).toFixed(1) + '%%' : '';
    });
    // Girado, el porcentaje necesita ALTO donde antes necesitaba ancho: "40.6%%" vertical
    // mide unos 40 px contra los 13 de un renglon horizontal. Por eso el umbral bajo el
    // cual no entra en la barra sube de 0.12 a 0.22 del maximo. Debajo de eso el
    // porcentaje se va afuera pegado al conteo, igual que antes.
    var bajoM = muestras.map(function (c) { return c / maxGlobal < 0.22; });
    var conteoTxt = muestras.map(function (c, j) {
      return bajoM[j] ? c + '  ' + pctM[j] : String(c);
    });
    var pctVisible = pctM.map(function (p, j) { return bajoM[j] ? '' : p; });
    var sinTexto = [];
    for (i = 0; i < 8; i++) { sinTexto.push([]); }

    // Las cuatro familias van en UNA sola llamada: el coste de un restyle lo fija el
    // numero de llamadas, no el tamano del payload.
    Plotly.restyle(gd, {
      x: vg.concat(vg, [CTX.grupos, CTX.grupos]),
      y: vu.concat(vn, [muestras, muestras]),
      text: sinTexto.concat([pctVisible, conteoTxt]),
    }, CTX.idx.violinUiti.concat(CTX.idx.violinEventos,
                                 [CTX.idx.barrasMuestras, CTX.idx.conteoMuestras]));

    ponerTitulos(gd, ' (n = ' + totalM + ')');
    return maxGlobal;
  }

  // Ventana y CIRCUITO de cada punto de la nube, mas la ventana de cada punto de la
  // trayectoria, cacheados para que mover el slider solo tenga que repintar opacidades.
  // El circuito hace falta porque el foco ya no es "la ventana" sino la INTERSECCION de
  // circuito y ventana, y esa pregunta no se puede contestar solo con la ventana.
  var VENTANA_PUNTO = [[], [], [], []], CIRCUITO_PUNTO = [[], [], [], []];
  var VENTANA_TRAY = [], CIRCUITO_FOCO = -1;

  // Opacidad POR PUNTO: solo el par CIRCUITO x VENTANA de interes va opaco y todo lo
  // demas queda de fondo -- otro circuito, otra ventana, o las dos cosas. Un punto de la
  // nube es exactamente ese par, asi que la pregunta "cual estoy mirando" tiene una sola
  // respuesta y no hace falta un tercer tono intermedio.
  // Sin circuito elegido no hay interseccion que resaltar, y ahi manda la ventana sola:
  // atenuar la nube entera dejaria al deslizador sin nada que decir.
  function pintarOpacidades(gd) {
    var w = ventanaActual(), i, g;
    var sinCircuito = CIRCUITO_FOCO < 0;
    var ops = [];
    for (g = 0; g < 4; g++) {
      var col = VENTANA_PUNTO[g], circ = CIRCUITO_PUNTO[g], arr = [];
      for (i = 0; i < col.length; i++) {
        arr.push(col[i] === w && (sinCircuito || circ[i] === CIRCUITO_FOCO)
                 ? CTX.opacidadFoco : CTX.opacidadFondo);
      }
      ops.push(arr);
    }
    // La trayectoria son las 11 ventanas del circuito elegido: ahi el circuito ya se
    // cumple por construccion y solo queda mirar la ventana.
    var opT = [];
    for (i = 0; i < VENTANA_TRAY.length; i++) {
      opT.push(VENTANA_TRAY[i] === w ? CTX.opacidadFoco : CTX.opacidadFondo);
    }
    // Nube y trayectoria en UNA sola llamada: el coste de un restyle lo fija el numero de
    // llamadas, no el tamano del payload.
    Plotly.restyle(gd, {'marker.opacity': ops.concat([opT])},
                   CTX.idx.mapa.concat([CTX.idx.trayectoria]));
  }

  // El punto de la ventana vigente en las dos series del doble eje, al triple. Mismo
  // recurso que la serie del cuaderno 01: `marker.size` es un arreglo y aqui solo se
  // reescribe, sin tocar ni los datos ni el color de los marcadores.
  // Va SEPARADO de `pintarOpacidades` a proposito: esto es barato -- 11 numeros por serie
  // -- y corre en vivo en cada paso del arrastre, mientras que repintar la opacidad de
  // 1.738 puntos va con retardo. Asi el punto grande sigue al deslizador sin que el
  // arrastre se sienta pesado.
  function pintarPuntoActivo(gd) {
    var w = ventanaActual();
    function tam(base) {
      return CTX.ventanas.map(function (_, i) {
        return i === w ? base * CTX.factorPuntoActivo : base;
      });
    }
    Plotly.restyle(gd, {'marker.size': [tam(CTX.serieTamUiti), tam(CTX.serieTamEventos)]},
                   [CTX.idx.serieUiti, CTX.idx.serieEventos]);
  }

  function aplicar() {
    var gd = d.getElementById(CTX.div);
    if (!gd || !gd._fullLayout) { return setTimeout(aplicar, 120); }

    var circuito = d.getElementById('tr-circuito').value;
    // El espacio es fijo -- eje x lineal, eje y logaritmico, minmax -- y ya no hay
    // controles que lo cambien: `CTX.espacios` trae uno solo. Se lee de ahi y no de dos
    // constantes escritas aqui, para que el dibujo no pueda contradecir a la geometria
    // con que se ajusto K-Means del lado de Python.
    var logx = CTX.espacios[0][0], logy = CTX.espacios[0][1];
    var etiquetas = CTX.gruposPorEspacio['0'];
    ETIQUETAS_VIGENTES = etiquetas;

    // La nube lleva TODAS las ventanas: es la trayectoria completa, y filtrarla dejaria
    // sin sentido las flechas que unen ventanas consecutivas. El reparto por grupo -- las
    // barras y los violines -- si se filtra, y vive en dibujarReparto().
    var mx = [[], [], [], []], my = [[], [], [], []], mt = [[], [], [], []];
    VENTANA_PUNTO = [[], [], [], []];
    CIRCUITO_PUNTO = [[], [], [], []];
    for (var k = 0; k < CELDAS.length; k++) {
      var ci = CELDAS[k][0], vi = CELDAS[k][1], g = etiquetas[k];
      var reg = CTX.porCircuito[CTX.circuitos[ci]];
      mx[g].push(reg.n[vi]); my[g].push(reg.u[vi]);
      mt[g].push(etiquetaPunto(ci, vi, g));
      // La ventana Y el circuito de cada punto quedan cacheados: mover el slider solo
      // repinta opacidades, no rehace la nube.
      VENTANA_PUNTO[g].push(vi);
      CIRCUITO_PUNTO[g].push(ci);
    }
    var ct = contorno(CTX.geometrias['0']);
    Plotly.restyle(gd, {z: [ct.z], x: [ct.x], y: [ct.y]}, [CTX.idx.contorno]);
    Plotly.restyle(gd, {x: mx, y: my, hovertext: mt}, CTX.idx.mapa);
    var maxMuestras = dibujarReparto(gd, etiquetas);

    // Trayectoria del circuito elegido, con el color del grupo en que cayo cada ventana.
    var xs = [], ys = [], colores = [], textos = [], rotulos = [], ventanaTray = [];
    // Series del doble eje: van las 11 ventanas, incluidas las de cero. Es una serie de
    // tiempo, y omitir los ceros haria parecer que esas ventanas no existieron.
    var serieU = [], serieN = [];
    // Grupo por ventana, para pintar y rotular los marcadores del doble eje. Arranca en -1
    // en todas: una ventana sin celda no tiene grupo, y ese caso es distinto de caer en el
    // grupo mas bajo.
    var grupoVentana = [];
    for (var k0 = 0; k0 < CTX.ventanas.length; k0++) { grupoVentana.push(-1); }
    if (circuito !== CTX.sinSeleccion) {
      var ci2 = CTX.circuitos.indexOf(circuito);
      var reg2 = CTX.porCircuito[circuito];
      serieU = reg2.u.slice(); serieN = reg2.n.slice();
      for (var k2 = 0; k2 < CELDAS.length; k2++) {
        if (CELDAS[k2][0] !== ci2) { continue; }
        var vi2 = CELDAS[k2][1], g2 = etiquetas[k2];
        xs.push(reg2.n[vi2]); ys.push(reg2.u[vi2]);
        // El punto resaltado lleva el color de SU grupo en esa ventana, no un color de
        // resaltado: el mismo circuito puede cambiar de grupo a lo largo de la trayectoria
        // y ese cambio es justamente lo que las flechas cuentan.
        colores.push(CTX.colores[g2]);
        ventanaTray.push(vi2);
        textos.push(etiquetaPunto(ci2, vi2, g2));
        rotulos.push(CTX.ventanas[vi2].etiqueta);
        grupoVentana[vi2] = g2;
      }
    } else {
      for (var k3 = 0; k3 < CTX.ventanas.length; k3++) { serieU.push(null); serieN.push(null); }
    }
    var colorPunto = grupoVentana.map(function (g) {
      return g >= 0 ? CTX.colores[g] : CTX.colorSinGrupo;
    });
    var customVentana = grupoVentana.map(function (g, w) {
      return [CTX.ventanas[w].periodo, g >= 0 ? CTX.grupos[g] : 'sin eventos'];
    });
    Plotly.restyle(gd, {y: [serieU], 'marker.color': [colorPunto],
                        customdata: [customVentana]}, [CTX.idx.serieUiti]);
    Plotly.restyle(gd, {y: [serieN], 'marker.color': [colorPunto],
                        customdata: [customVentana]}, [CTX.idx.serieEventos]);
    // Solo se rotula el arranque y el final: con 11 ventanas cercanas las etiquetas se
    // encimaban y se leian como una sola ("V1011"). El resto sale del hover.
    var visibles = rotulos.map(function (r, i) {
      return (i === 0 || i === rotulos.length - 1) ? r : '';
    });
    Plotly.restyle(gd, {x: [xs], y: [ys], 'marker.color': [colores],
                        text: [visibles], hovertext: [textos]}, [CTX.idx.trayectoria]);

    // Con un circuito elegido la nube de los otros 207 se atenua: su trayectoria son 11
    // puntos contra 1738, y a igual opacidad se pierde adentro. El contorno de membresia
    // se atenua junto con ella para que el fondo no gane peso al vaciarse la nube.
    var hay = circuito !== CTX.sinSeleccion;
    CIRCUITO_FOCO = hay ? CTX.circuitos.indexOf(circuito) : -1;
    VENTANA_TRAY = ventanaTray;
    pintarOpacidades(gd);
    pintarPuntoActivo(gd);
    Plotly.restyle(gd, {opacity: hay ? 0.14 : 0.28}, [CTX.idx.contorno]);

    // Las flechas son anotaciones de layout, no una traza. En un eje logaritmico Plotly
    // espera las coordenadas YA en log10, asi que se convierten segun el tipo de cada eje.
    var refX = 'x' + CTX.ejes.mapaX.slice(5), refY = 'y' + CTX.ejes.mapaY.slice(5);
    var flechas = [];
    for (var i2 = 0; i2 + 1 < xs.length; i2++) {
      flechas.push({
        x: logx ? Math.log10(xs[i2 + 1]) : xs[i2 + 1],
        y: logy ? Math.log10(ys[i2 + 1]) : ys[i2 + 1],
        ax: logx ? Math.log10(xs[i2]) : xs[i2],
        ay: logy ? Math.log10(ys[i2]) : ys[i2],
        xref: refX, yref: refY, axref: refX, ayref: refY,
        showarrow: true, arrowhead: 3, arrowsize: 1.1, arrowwidth: 1.4,
        arrowcolor: 'rgba(120,20,20,0.75)', standoff: 10, startstandoff: 10, text: '',
      });
    }
    // Cada violin sigue el log de SU propia variable, no el del eje en que esta dibujado.
    // Las barras y el doble eje quedan siempre lineales: ahi hay ceros, que no existen en log.
    var tx = logx ? 'log' : 'linear', ty = logy ? 'log' : 'linear';
    var cambios = {annotations: fig_anotaciones.concat(flechas)};
    cambios[CTX.ejes.mapaX + '.type'] = tx;
    cambios[CTX.ejes.mapaY + '.type'] = ty;
    cambios[CTX.ejes.violinUiti + '.type'] = ty;
    cambios[CTX.ejes.violinEventos + '.type'] = tx;
    // Las barras rotulan por fuera: sin margen arriba, el numero de la barra mas alta se
    // mete en el titulo del panel. El margen sale del dato, no del autorango. Atencion:
    // este bloque se arma con formateo de cadena, de modo que un simbolo de porcentaje
    // suelto en un comentario produce "not enough arguments for format string".
    cambios[CTX.ejes.barrasMuestras + '.range'] = [0, maxMuestras * 1.18];
    // Barras y violines ya solo describen UNA ventana, asi que sus escalas se fijan sobre
    // el total: con autorango, una ventana con la mitad de circuitos se veria igual de
    // alta y mover el slider no contaria nada. Cada violin sigue la extension de SU propia
    // variable, no la del eje en que esta dibujado.
    var exG = CTX.extension;
    cambios[CTX.ejes.violinUiti + '.range'] = limEje(exG[2], exG[3], logy);
    cambios[CTX.ejes.violinEventos + '.range'] = limEje(exG[0], exG[1], logx);
    Plotly.relayout(gd, cambios);

    dibujarMapa(gd, circuito);

    // El reparto de vanos por grupo ya esta en el grafico de barras: repetirlo aqui solo
    // alargaba el aviso.
    d.getElementById('tr-aviso').textContent = (circuito === CTX.sinSeleccion
      ? 'Seleccione un circuito para ver su trayectoria.'
      : circuito + ': ' + xs.length + ' de ' + CTX.ventanas.length +
        ' ventanas con eventos, ' + flechas.length + ' tramos.');
  }

  // Los titulos de los subplots tambien son anotaciones: hay que conservarlos al
  // reescribir `annotations` con las flechas, o desaparecen en el primer cambio.
  var fig_anotaciones = (function () {
    var gd = d.getElementById(CTX.div);
    return (gd && gd.layout && gd.layout.annotations) ? gd.layout.annotations.slice() : [];
  })();

  ['tr-circuito'].forEach(function (id) {
    var el = d.getElementById(id);
    if (el) { el.addEventListener('change', aplicar); }
  });
  // El slider repinta el mapa y rehace el reparto de la ventana. No cambia la particion:
  // los centroides siguen ajustados sobre la ventana completa, solo cambia que celdas se
  // cuentan. El reparto va con retardo porque su restyle es el mas caro de la figura y el
  // evento 'input' se dispara en cada paso del arrastre; el mapa se mantiene inmediato.
  var slider = d.getElementById('tr-ventana');
  if (slider) {
    var pendiente = null, cuadro = null;
    slider.addEventListener('input', function () {
      var gd = d.getElementById(CTX.div);
      if (!gd || !gd._fullLayout) { return; }
      // `input` se dispara en CADA paso del arrastre, y cada paso encargaba su
      // dibujado: 472 ms de CPU en un arrastre de seis ventanas, medido. Con un
      // cuadro de por medio se dibuja una vez por refresco de pantalla y gana el
      // ultimo estado, que es lo que el usuario esta pidiendo mientras arrastra.
      if (cuadro !== null) { return; }
      cuadro = requestAnimationFrame(function () {
        cuadro = null;
        dibujarAlVuelo(gd);
      });
    });

    // Lo que sigue al dedo mientras se arrastra. Lo caro -- el reparto y la opacidad
    // de 1.738 puntos -- espera al antirrebote de abajo.
    function dibujarAlVuelo(gd) {
      dibujarMapa(gd, d.getElementById('tr-circuito').value);
      // El punto grande de las series sigue al deslizador EN VIVO, como el mapa: son 22
      // numeros. Lo caro -- la opacidad de 1.738 puntos y el reparto -- sigue con retardo.
      pintarPuntoActivo(gd);
      if (pendiente) { clearTimeout(pendiente); }
      pendiente = setTimeout(function () {
        pendiente = null;
        if (ETIQUETAS_VIGENTES) { dibujarReparto(gd, ETIQUETAS_VIGENTES); }
        pintarOpacidades(gd);
      }, 140);
    }
  }
  aplicar();
  // MapLibre inicializa de forma asincrona: un restyle/relayout disparado antes de que el
  // subplot de mapa este listo se pierde en silencio -- el fondo carga pero las lineas del
  // circuito no aparecen. Se repite el dibujado un par de veces despues del arranque; es
  // idempotente, asi que repetirlo no tiene costo mas alli de esas dos pasadas.
  [700, 2000].forEach(function (ms) {
    setTimeout(function () {
      var gd = d.getElementById(CTX.div);
      var sel = d.getElementById('tr-circuito');
      if (gd && gd._fullLayout && sel) {
        dibujarMapa(gd, sel.value, true);
        encuadrarCircuito(gd, sel.value);
      }
    }, ms);
  });

  // La figura es responsive: al cambiar el tamano de la ventana se redibuja y el mapa pasa
  // a tener otro tamano en pixeles. El encuadre se rehace con la medida nueva, o el
  // circuito queda recortado. Con retardo, porque 'resize' se dispara en cada cuadro del
  // arrastre.
  var reencuadre = null;
  window.addEventListener('resize', function () {
    if (reencuadre) { clearTimeout(reencuadre); }
    reencuadre = setTimeout(function () {
      reencuadre = null;
      var gd = d.getElementById(CTX.div);
      var sel = d.getElementById('tr-circuito');
      if (gd && gd._fullLayout && sel) { encuadrarCircuito(gd, sel.value); }
    }, 200);
  });
})();
</script>
''' % json.dumps(CONTEXTO, separators=(',', ':'))

    # include_plotlyjs=True embebe plotly.js en esta misma salida: el panel, la figura y su
    # libreria viajan juntos, de modo que el tablero se ve igual exportado a HTML o en nbviewer.
    # `default_width='100%'` solo surte efecto porque la figura NO lleva `width` (ver la celda
    # anterior), y `responsive` la recalcula al cambiar el tamano de la ventana.
    FIGURA_HTML = pio.to_html(fig, include_plotlyjs=True, full_html=False, div_id=DIV_FIGURA,
                              default_width='100%', config={'responsive': True})

    CSS_DOS_COLUMNAS = '''
<style>
  /* Los controles a la izquierda y las figuras a la derecha, en vez de una barra
     horizontal encima de una figura de 960 a 1.700 px de alto: asi elegir un circuito y
     ver que le hace al mapa dejan de estar en extremos opuestos del scroll. */
  .cuerpo-2col {
    display: flex; align-items: flex-start; gap: 14px;
    width: 100%; box-sizing: border-box;
  }
  /* `min-width: 0` apaga el `min-width: auto` que trae todo hijo de flex. Sin el, el
     ancho minimo del div de plotly manda sobre el 70% declarado y la pagina scrollea a
     lo ancho: el 30/70 se escribe pero no se cumple. */
  /* El ancho de los controles viaja en una variable CSS con 30% por defecto: este mismo
     bloque va COPIADO en los cuatro cuadernos y una prueba exige que las copias sean
     identicas, asi que un tablero que quiera otro reparto lo dice en SU marcado --
     `<div class="cuerpo-2col" style="--ancho-controles: 25%">` -- y no aqui. */
  .cuerpo-2col > .col-controles {
    flex: 0 0 var(--ancho-controles, 30%); max-width: var(--ancho-controles, 30%);
    min-width: 0; box-sizing: border-box;
  }
  /* Y las figuras se quedan con lo que sobra, sea cual sea ese reparto. `flex: 1 1 0`
     con `min-width: 0` es lo que hace que "lo que sobra" no dependa del ancho minimo del
     contenido: el div de plotly tiene uno propio y sin esto manda el. */
  .cuerpo-2col > .col-figuras { flex: 1 1 0; min-width: 0; box-sizing: border-box; }
  /* El panel de cada tablero es una barra `display:flex` pensada para el ancho entero;
     en una columna del 30% va en vertical, o cada control se queda en su ancho minimo y
     el conjunto hace una escalera con huecos. Se le llama por el PREFIJO de su clase y
     no por su nombre -- son cuatro distintos: panel-clima, panel-agrup, panel-tray,
     panel-v -- para que este mismo bloque sirva para los cuatro cuadernos. */
  .cuerpo-2col > .col-controles > [class^="panel-"] {
    flex-direction: column; flex-wrap: nowrap; align-items: stretch; max-width: 100%;
  }
  /* Y sus controles dejan de exigir un ancho que la columna ya no tiene. */
  .cuerpo-2col > .col-controles select,
  .cuerpo-2col > .col-controles input,
  .cuerpo-2col > .col-controles button { max-width: 100%; min-width: 0; }
  /* Las filas del panel se parten cuando no caben, en vez de salirse por la derecha. */
  .cuerpo-2col > .col-controles > [class^="panel-"] > div { flex-wrap: wrap; }
  /* Medido en 01_clima: sus filas de barra deslizante traen `min-width` y
     `white-space: nowrap` EN LINEA -- un rotulo de 520 px y un hueco de 300 px reservado
     para que el numero no haga saltar la barra --, dimensionados para el ancho entero. En
     una columna de 370 px eso sacaba un control hasta 180 px fuera. Un atributo `style`
     solo lo vence `!important`, y este es el unico sitio del bloque donde se usa. */
  .cuerpo-2col > .col-controles [style*="min-width"] { min-width: 0 !important; }
  .cuerpo-2col > .col-controles label,
  .cuerpo-2col > .col-controles span { white-space: normal !important; }
  /* Pero la barra conserva un ancho con el que se pueda arrastrar. */
  .cuerpo-2col > .col-controles input[type="range"] { min-width: 140px; }
  /* Y las tiras de escala, que el JS arma con `display:inline-flex` EN LINEA y sin
     `flex-wrap`: medido en 01_clima, se salian 46 px por la derecha a 1.280 y a 1.512 px
     de ventana, y a 1.900 no -- justo el tipo de fallo que solo aparece en la pantalla
     de otro. Un `inline-flex` que no puede partirse no encoge: se sale entero. */
  .cuerpo-2col > .col-controles [style*="inline-flex"] {
    flex-wrap: wrap !important; max-width: 100% !important;
  }
  .cuerpo-2col > .col-figuras > div { width: 100%; }
</style>
'''

    # El panel y la figura dejan de apilarse: van en una fila de dos columnas. El JS queda
    # FUERA de la fila -- no pinta nada, solo cuelga los manejadores -- y sigue encontrando
    # sus elementos por id, que no cambian al envolverlos.
    PANEL_COMPLETO = CSS_DOS_COLUMNAS + (
        '<div class="cuerpo-2col">'
        f'<div class="col-controles">{PANEL_HTML}</div>'
        f'<div class="col-figuras">{FIGURA_HTML}</div>'
        '</div>'
    ) + PANEL_JS


    # El MISMO html, envuelto en un documento minimo, escrito a disco y abierto en el navegador:
    # alli el tablero usa todo el ancho de la pantalla en vez del de la celda. No se vuelve a
    # serializar nada -- se reusa PANEL_COMPLETO, que ya trae plotly.js embebido -- de modo que
    # el archivo funciona sin conexion y sin el cuaderno.
    def exportar_y_abrir(html_panel, *, abrir=True):
        import webbrowser

        _por_defecto = REPO_ROOT / 'reports' / 'paneles' / '03_uiti_vano_trayectorias_circuitos.html'
        destino = Path(ruta_html) if ruta_html is not None else _por_defecto
        destino.parent.mkdir(parents=True, exist_ok=True)
        documento = (
            '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>Trayectoria y agrupamiento de circuitos con ventana deslizante</title>\n'
            # margen 0 y un div al 100%: sin esto el navegador deja el margen por defecto del
            # body y la figura no llega a los bordes de la pantalla.
            '<style>html,body{margin:0;padding:12px;box-sizing:border-box;'
            'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;'
            'color:#2b2b2b;background:#fff;}'
            f'#{DIV_FIGURA}{{width:100%;}}</style>\n</head>\n<body>\n'
            + html_panel + '\n</body>\n</html>\n'
        )
        destino.write_text(documento, encoding='utf-8')
        mb = destino.stat().st_size / 1024 ** 2
        print(f'panel autocontenido escrito en {_corta(destino, REPO_ROOT)} ({mb:,.1f} MB)')
        if abrir:
            webbrowser.open(destino.resolve().as_uri())
            print('abriendo en el navegador por defecto -- '
                  f'pesa {mb:,.0f} MB, de modo que la primera carga puede tardar unos segundos')
        else:
            print('ABRIR_EN_NAVEGADOR = False: no se abre nada, el archivo queda escrito')
        return destino


    RUTA_PANEL = exportar_y_abrir(PANEL_COMPLETO, abrir=ABRIR_EN_NAVEGADOR)

    def guardar_tabla(destino=None):
        """Escribe TABLA en reports/reportescircuitos/artifacts/.

    Es la salida tabular del tablero: mismo esquema y mismo orden que la grilla que el panel
    dibuja, para que el archivo y la figura cuenten lo mismo.
    """
        if destino is None:
            destino = (REPO_ROOT / 'reports' / 'reportescircuitos' / 'artifacts' /
                       'uiti_ventanas_deslizantes.csv')
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        TABLA.to_csv(destino, index=False)
        return destino


    ruta_csv = guardar_tabla()
    print(f'{len(TABLA)} filas -> {_corta(ruta_csv, REPO_ROOT)}')

    # Circuitos con mas movimiento entre ventanas: los que mas se van a notar en el mapa.
    resumen = (TABLA.groupby('circuito')
               .agg(ventanas_con_eventos=('num_eventos', lambda s: int((s > 0).sum())),
                    uiti_total=('uiti_acumulado', 'sum'),
                    uiti_max_ventana=('uiti_acumulado', 'max'))
               .sort_values('uiti_total', ascending=False))
    resumen.head(10)

    return RUTA_PANEL
