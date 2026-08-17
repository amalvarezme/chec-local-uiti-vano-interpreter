"""El tablero de trayectorias de vano, con ventana deslizante y mapa.

## De donde sale este modulo

Es el cuaderno `04_uiti_vano_trayectorias_vano.ipynb`, movido aqui. Ver
`chec_tableros.clima` para el porque del traslado y para el criterio de reparto
entre constantes de modulo y tuberia dentro de `construir()`.

## Lo propio de este tablero

Aqui la unidad del K-Means es el VANO, no el circuito, asi que el color del mapa
es la membresia del agrupamiento y no un corte fijo de UITI. Esa geometria es la
misma que replican el cuaderno 05 y el simulador, y desde el 2026-08-15 viaja
versionada en `data/geometria_kmeans_014_v1.json`, producida por
`scripts/exportar_geometria.py` a partir del CSV. Ya no se extrae de la salida
guardada de este cuaderno.

## Lo unico que cambia respecto del cuaderno

- `display(HTML(...))` desaparece: no hay kernel ni celda donde pintar.
- `REPO_ROOT`, el destino del HTML y el abrir-en-navegador los pasa quien llama.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import pyarrow.csv as pacsv
import shapely
from plotly.subplots import make_subplots
from sklearn.cluster import KMeans
from sklearn.preprocessing import MinMaxScaler, StandardScaler

# Ademas de pintar el panel dentro del cuaderno, escribe el mismo HTML autocontenido en
# reports/paneles/ y lo abre en el navegador, donde el tablero usa todo el ancho de la
# pantalla. En Databricks se pone en False: dentro de un job no hay navegador.

NOMBRES_GRUPOS = ['Bajo', 'Medio', 'Medio-Alto', 'Alto']
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
COLOR_SIN_EVENTO = 'rgb(0,0,0)'
COLOR_TRAFO = '#f59e0b'
COLOR_SWITCH = '#7c3aed'

# Cupos de resaltado. Cada vano marcado toma un color propio que se repite en las tres
# figuras -- nube, mapa y evolucion -- y una sola entrada de leyenda que las arrastra a
# todas. Los marcados que sobran se resaltan igual, pero en gris y sin serie propia.
#
# TREINTA y ya no ocho, el mismo `MAX_VANOS_SERIE` del cuaderno 06. Son dos numeros
# encadenados: la marca automatica pone hasta quince, y el usuario puede seguir agregando
# vanos con la casilla o tocandolos en el mapa sin tope. Con ocho cupos, siete de los quince
# auto-marcados ya quedaban en gris y sin serie -- el tablero marcaba quince y contaba ocho
# --, y con quince el primer vano agregado a mano se quedaba fuera. El doble deja sitio a
# los quince automaticos mas quince elegidos a mano.
MAX_VANOS_RESALTADOS = 30
# La paleta es la MISMA lista del cuaderno 06 y en el mismo orden: un vano que es azul en un
# cuaderno tiene que seguir siendo azul en el otro. Son quince colores para treinta cupos
# porque no hay quince tonos mas que sean de verdad distinguibles entre si; la paleta se
# recorre en circulo y la SEGUNDA vuelta va con trazo discontinuo (`DASH_CUPO`), que es un
# canal que aqui estaba libre. Preferible a inventar tonos que se confundirian de a pares.
COLORES_VANOS = ['#0072b2', '#009e73', '#cc79a7', '#56b4e9', '#e69f00', '#8c564b',
                 '#d55e00', '#6a3d9a', '#17becf', '#666666',
                 '#b2df8a', '#bcbd22', '#004949', '#920000', '#b39ddb']
# El color y el patron de CADA cupo, ya desplegados a `MAX_VANOS_RESALTADOS`. Se calculan
# una vez y no en cada sitio que indexa por cupo: son cuatro sitios -- la nube, las dos
# series y las flechas del panel -- y un `% len(...)` olvidado en uno solo bastaria para
# que el mismo vano saliera de dos colores en la misma figura.
COLOR_CUPO = [COLORES_VANOS[_s % len(COLORES_VANOS)] for _s in range(MAX_VANOS_RESALTADOS)]
DASH_CUPO = ['solid' if _s < len(COLORES_VANOS) else 'dash'
             for _s in range(MAX_VANOS_RESALTADOS)]
COLOR_OTROS_ELEGIDOS = '#475569'
COLOR_SIN_GRUPO = '#94a3b8'
# Cuantos vanos se marcan SOLOS. Al elegir circuito, los de mayor UITI acumulado en TODO el
# periodo; al mover el deslizador, los de mayor UITI en esa ventana. Antes se marcaban
# TODOS los que tuvieran un evento en la ventana, que en un circuito activo son decenas: la
# leyenda crecia a seis renglones, las flechas se cruzaban y el panel dejaba de senialar
# nada en particular. Los mismos dos numeros que usa el cuaderno 06.
TOP_VANOS_VENTANA = 15
# Los margenes laterales de la figura. Con nombre y no escritos dentro del `margin`
# porque la barra del boton de encuadre los necesita para su `calc()`: el borde izquierdo
# del mapa es `margen_izq + x0 * (ancho - margen_izq - margen_der)`, y si el margen y la
# barra se declararan por separado, mover uno desalinearia la otra sin fallar.
MARGEN_IZQ = 90
MARGEN_DER = 60

TOP_VANOS_PERIODO = 15
# El mismo rojo con que el cuaderno 06 dibuja su panel "Perfil del circuito":
# los dos tableros contestan ahi la misma pregunta y se miran uno al lado del otro.
COLOR_BARRA_PERFIL = 'rgb(203,24,29)'
# El punto de la VENTANA VIGENTE en las series de evolucion se dibuja al triple, como el
# dia vigente en la serie del cuaderno 01. `marker.size` es un ARRAY por eso: mover el
# deslizador solo reescribe ese arreglo y el punto grande viaja con el.
SERIE_TAM_UITI = 9
SERIE_TAM_EVENTOS = 8
FACTOR_PUNTO_ACTIVO = 3
# La nube tiene DOS niveles de opacidad y no la cascada de tres de antes. El sujeto de la
# figura es el circuito elegido en la ventana elegida, asi que sus celdas -- y solo esas --
# van opacas; el resto queda de fondo, sea de otro circuito, de otra ventana, o de las dos
# cosas. La cascada vieja graduaba nube / circuito / cupos en tres tonos, y con la pregunta
# reducida a "cual es la celda de interes" no queda nada que graduar: los vanos marcados se
# siguen distinguiendo por tamano y por su anillo de color, no por opacidad.
# Sin circuito elegido no hay interseccion posible, y ahi manda la ventana sola: si no, la
# nube entera quedaria uniformemente de fondo y el deslizador no diria nada.
OPACIDAD_FOCO = 1.0
OPACIDAD_FONDO = 0.30
# Estilo del mapa, TOMADO DEL CUADERNO 01 (`01_uiti_vano_clima`, celda 4). Los cuatro
# mapas del proyecto dibujan los mismos objetos sobre la misma geografia, asi que un
# transformador, un vano con eventos y uno sin ellos tienen que medir lo mismo en todos:
# de otro modo el mismo circuito se lee como dos circuitos distintos al pasar de cuaderno.
# 01 subio los equipos de 6/5 a 14/12 px y la capa de vano de 3.5 a 7.0 px cuando su figura
# doblo de alto; aqui se adoptan esos valores, que es lo que hace comparables los mapas.
# Contrapartida: este mapa es mas bajo que el de 01, asi que el mismo trazo pesa mas sobre
# el. Se asume: la comparacion entre cuadernos vale mas que el equilibrio de cada uno.
# El resaltado del mapa es un 40% mas ancho que el trazo normal, no un grosor suelto:
# derivarlo evita que cambiar uno deje al otro atras. 01 no tiene vanos marcados, asi que
# no fija este ancho; lo que se hereda de el es la base de la que sale.
ANCHO_MAPA = 7.0                 # vano CON eventos, del color de su grupo
ANCHO_MAPA_RESALTE = round(ANCHO_MAPA * 1.4, 2)
ANCHO_SIN_EVENTOS = 1.5          # estructura del circuito: el vano sin eventos
TAM_TRAFO = 14
TAM_SWITCH = 12

# El recuadro del vano marcado, con los MISMOS valores del cuaderno 06
# (`cajas_seleccion_por_clase` en src/chec_local_interpreter/ventanas_015.py): mismos
# colores, misma opacidad y el mismo rectangulo girado a la direccion del propio vano. Los
# dos tableros senialan el mismo objeto sobre el mismo mapa, y dos resaltados de distinto
# tamanio o distinto color se leen como dos cosas distintas.
# El lado minimo se abre en torno al EJE del vano y el margen se suma despues a cada lado,
# los dos en el marco del vano: un tramo no tiene grosor, asi que a lo ancho la caja
# siempre parte de cero, y sin lado minimo seria una astilla invisible.
#
# El relleno lleva el color del GRUPO KMeans del propio vano y ya no un amarillo suelto. El
# amarillo contestaba "esto es lo que estoy mirando", y esa pregunta ya la contestan el
# halo blanco y el trazo mas ancho; con el color del grupo, el recuadro contesta ademas en
# que nivel cayo -- la misma lectura que su linea, pero en una mancha de ~50 m de lado que
# se sigue viendo al zoom en que la linea deja de distinguirse de sus vecinas.
COLORES_CAJA_SELECCION = list(COLORES_GRUPOS)
# El marcado que en ESTA ventana no tiene celda no tiene grupo, y eso no es el grupo mas
# bajo: es la ausencia del dato. Mismo gris con que la evolucion pinta sus puntos sin celda.
COLOR_CAJA_SIN_GRUPO = COLOR_SIN_GRUPO
OPACIDAD_CAJA_SELECCION = 0.5
LADO_MINIMO_CAJA = 0.00045       # grados ~= 50 m
MARGEN_CAJA = 0.00009            # grados ~= 10 m


def find_repo_root():
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / 'data/Indicadores_vano_v3.csv').exists():
            return candidate
    raise FileNotFoundError('No se encontro data/Indicadores_vano_v3.csv subiendo desde el cwd')




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


    def _norm_id(serie):
        return (serie.astype('string').str.strip().str.replace(r'\.0$', '', regex=True)
                .replace({'': pd.NA, '<NA>': pd.NA, 'nan': pd.NA, 'None': pd.NA}))


    # Mismo lector que el 03. El CSV completo trae ~270 columnas y solo se usan cuatro.
    COLUMNAS_BASE = ['CIRCUITO', 'FID_VANO', 'UITI_VANO', 'FECHA']


    def leer_eventos(columnas=COLUMNAS_BASE):
        """Lee el CSV de eventos por bloques y devuelve solo `columnas`, en ese orden.

    Se usa el lector incremental de pyarrow y no `pd.read_csv`. El resultado es el mismo
    valor por valor, pero `pd.read_csv(engine='pyarrow')` materializa el archivo de 566 MB
    antes de descartar las columnas que no se usan: medido, 826 MB de pico de memoria contra
    109 MB por bloques, a cambio de 0,2 s mas de lectura.
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
    df['FID_VANO'] = _norm_id(df['FID_VANO'])

    CIRCUITOS = sorted(df['CIRCUITO'].astype(str).unique())
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

    # Ventanas IDENTICAS a las del 03: cada mes aporta el mes calendario completo y la cruzada
    # del dia 15 al 15 del siguiente; ordenadas por fecha de inicio quedan alternadas.
    _meses = pd.period_range(df['FECHA'].min(), df['FECHA'].max(), freq='M')
    _fin = _meses[-1].to_timestamp(how='end').normalize() + pd.Timedelta(days=1)
    _cortes = []
    for _k, _m in enumerate(_meses):
        _ini = _m.to_timestamp()
        _f = _meses[_k + 1].to_timestamp() if _k + 1 < len(_meses) else _fin
        _cortes.append((_ini, _f))
        _cortes.append((_ini + pd.Timedelta(days=14), _f + pd.Timedelta(days=14)))
    _cortes = sorted(c for c in _cortes if c[1] <= _fin)

    VENTANAS = [
        {'i': k, 'desde': a, 'hasta_excl': b, 'etiqueta': f'V{k + 1}',
         'periodo': f'{a.date()} a {(b - pd.Timedelta(days=1)).date()}'}
        for k, (a, b) in enumerate(_cortes)
    ]

    print(f'{len(df):,} eventos | {len(CIRCUITOS)} circuitos | '
          f'{df["FID_VANO"].nunique():,} vanos | {len(VENTANAS)} ventanas')
    for v in VENTANAS:
        print(f'  {v["etiqueta"]:>3s}  {v["periodo"]}')


    # Una fila por par vano x ventana con eventos. A diferencia de 02, las ventanas no
    # son meses calendario, asi que no se pueden sumar meses: cada ventana se recorta aparte.
    _piezas = []
    for v in VENTANAS:
        dentro = df[(df['FECHA'] >= v['desde']) & (df['FECHA'] < v['hasta_excl'])]
        agg = (dentro.groupby(['CIRCUITO', 'FID_VANO'])['UITI_VANO']
               .agg(uiti_acumulado='sum', num_eventos='count').reset_index())
        agg['ventana'] = v['etiqueta']
        agg['ventana_i'] = v['i']
        _piezas.append(agg)

    TABLA = pd.concat(_piezas, ignore_index=True)
    TABLA['uiti_acumulado'] = TABLA['uiti_acumulado'].round(3)
    TABLA = TABLA[TABLA['uiti_acumulado'] > 0].reset_index(drop=True)
    TABLA = TABLA.sort_values(['CIRCUITO', 'FID_VANO', 'ventana_i']).reset_index(drop=True)

    VANOS_POR_CIRCUITO = {
        c: sorted(g['FID_VANO'].unique().tolist())
        for c, g in TABLA.groupby(TABLA['CIRCUITO'].astype(str))
    }
    print(f'{len(TABLA):,} celdas vano x ventana con eventos | '
          f'{TABLA["FID_VANO"].nunique():,} vanos distintos')
    print(f'vanos por circuito -> mediana {int(np.median([len(v) for v in VANOS_POR_CIRCUITO.values()]))}'
          f' | max {max(len(v) for v in VANOS_POR_CIRCUITO.values())}')
    TABLA.head()

    XY = TABLA[['num_eventos', 'uiti_acumulado']].to_numpy(dtype=float)


    def geometria(log_x, log_y, prep):
        """K-Means a 4 grupos sobre TODAS las celdas; devuelve solo la geometria.

    Se ajusta UNA sola vez, sobre el unico espacio del cuaderno: elegir circuito o vanos
    no reajusta las fronteras, solo cambia que se resalta.
    """
        X = XY.copy()
        if log_x:
            X[:, 0] = np.log10(X[:, 0])
        if log_y:
            X[:, 1] = np.log10(X[:, 1])
        esc = PREPROCESOS[prep]().fit(X)
        modelo = KMeans(n_clusters=4, random_state=SEMILLA, n_init=10).fit(esc.transform(X))

        off, sc = ((esc.data_min_, esc.data_range_) if prep == 'minmax'
                   else (esc.mean_, esc.scale_))
        off, sc = np.round(off, 6), np.round(sc, 6)
        cen = np.round(modelo.cluster_centers_, 6)

        Z = (X - off) / sc
        cruda = (((Z[:, None, :] - cen[None, :, :]) ** 2).sum(axis=2)).argmin(axis=1)
        difieren = int((cruda != modelo.predict(esc.transform(X))).sum())
        assert difieren <= max(5, int(0.001 * len(cruda))), (
            f'{difieren} de {len(cruda)} no coinciden con predict(): no es un empate de frontera')

        orden = list(np.argsort([np.median(XY[cruda == c, 1]) for c in range(4)]))
        return {'logs': [bool(log_x), bool(log_y)], 'offset': off.tolist(),
                'scale': sc.tolist(), 'centroides': cen[orden].tolist()}, difieren


    GEOMETRIAS, _dif = {}, 0
    for e, (lx, ly, prep) in enumerate(ESPACIOS):
        GEOMETRIAS[str(e)], d = geometria(lx, ly, prep)
        _dif += d

    # Extension FIJA: los ejes y la grilla del contorno no dependen de la seleccion.
    EXTENSION = [float(XY[:, 0].min()), float(XY[:, 0].max()),
                 float(round(XY[:, 1].min(), 4)), float(round(XY[:, 1].max(), 4))]

    print(f'K-Means ajustado una vez (eje x lineal, eje y logaritmico, minmax) '
          f'sobre {len(XY):,} celdas')
    print(f'puntos sobre la frontera que mueve el redondeo: {_dif} en total')
    print(f'extension fija -> eventos [{EXTENSION[0]:.0f}, {EXTENSION[1]:.0f}] | '
          f'UITI [{EXTENSION[2]:.2f}, {EXTENSION[3]:,.0f}]')

    # Misma geometria y mismo cruce que el mapa del reporte y el del 03.
    # columns= limita la lectura a lo que se usa: el shapefile trae 44 columnas y aqui solo hacen
    # falta G3E_FID (el id del vano) y CIRCUITO; la geometria viene siempre. Leerlo completo
    # cuesta 0,75 s contra 0,08 s, sobre las mismas 60.053 filas.
    _lineas = gpd.read_file(REPO_ROOT / 'data' / 'GEO' / 'MVLINSEC.shp',
                            columns=['G3E_FID', 'CIRCUITO'])
    if str(_lineas.crs) != 'EPSG:4326':
        _lineas = _lineas.to_crs('EPSG:4326')
    _lineas['FID_VANO_GEO'] = _norm_id(_lineas['G3E_FID'])
    _utiles = _lineas[_lineas['CIRCUITO'].astype(str).isin(set(CIRCUITOS))]

    # Las coordenadas salen de UNA pasada con shapely.get_coordinates, en vez de pedir `.xy`
    # geometria por geometria: sobre los 60.053 tramos eso baja de 0,51 s a 0,13 s. El redondeo
    # sigue siendo el round() de Python sobre la lista plana, no np.round: los dos resuelven de
    # forma distinta los empates exactos en el quinto decimal, y el resultado tiene que ser
    # identico al anterior valor por valor.
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
    # Extremos por circuito: con ellos el navegador encuadra el mapa sobre el tamano real del
    # circuito y el tamano real del lienzo, en vez de usar un zoom fijo.
    for _info in GEO_POR_CIRCUITO.values():
        _la = [v for l in _info['lat'] for v in l]
        _lo = [v for l in _info['lon'] for v in l]
        _info['bounds'] = [round(min(_la), 5), round(max(_la), 5),
                           round(min(_lo), 5), round(max(_lo), 5)]


    def _equipo(nombre):
        ruta = REPO_ROOT / 'data' / 'GEO' / nombre
        if not ruta.exists():
            return {}
        # Igual que con MVLINSEC: de las 57 columnas de transformadores y las 49 de switches solo
        # se usa CIRCUITO, y la geometria viaja aparte.
        g = gpd.read_file(ruta, columns=['CIRCUITO'])
        if str(g.crs) != 'EPSG:4326':
            g = g.to_crs('EPSG:4326')
        g = g[g['CIRCUITO'].astype(str).isin(set(CIRCUITOS))]
        g = g[g.geometry.notna() & ~g.geometry.is_empty]
        return {c: {'lat': [round(float(p.y), 5) for p in gg.geometry],
                    'lon': [round(float(p.x), 5) for p in gg.geometry]}
                for c, gg in g.groupby(g['CIRCUITO'].astype(str))}


    TRAFOS = _equipo('GDBCHEC_TRANSFOR.shp')
    SWITCHES = _equipo('SWITCHES.shp')

    # UITI y eventos por vano y ventana, indexado para el JS.
    UITI_VENTANA = [{} for _ in VENTANAS]
    for _fid, _vi, _u, _n in zip(TABLA['FID_VANO'], TABLA['ventana_i'],
                                 TABLA['uiti_acumulado'], TABLA['num_eventos']):
        UITI_VENTANA[int(_vi)][str(_fid)] = [float(_u), int(_n)]

    # El mapa NO tiene escala propia ni umbrales: pinta cada vano con el color del grupo de
    # K-Means en que cae su celda de esa ventana. Asi el color significa lo mismo en el mapa,
    # en la nube, en las barras y en los violines, y es comparable entre circuitos, porque los
    # centroides son unicos para todo el dataset. La membresia se evalua en el navegador, que
    # es donde se conoce el espacio (log y preproceso) elegido en cada momento.
    _fids_geo = {f for _i in GEO_POR_CIRCUITO.values() for f in _i['fids']}
    _celdas_geo = sum(1 for u in UITI_VENTANA for f in u if f in _fids_geo)

    print(f'{len(GEO_POR_CIRCUITO)} circuitos con geometria | '
          f'{sum(len(v["fids"]) for v in GEO_POR_CIRCUITO.values()):,} tramos')
    print(f'equipos: {sum(len(v["lat"]) for v in TRAFOS.values()):,} transformadores | '
          f'{sum(len(v["lat"]) for v in SWITCHES.values()):,} switches')
    print(f'{_celdas_geo:,} celdas vano x ventana caen sobre un vano con geometria '
          f'(se pintan con el color de su grupo)')

    # El periodo que el tablero cubre de verdad: desde el arranque de la PRIMERA ventana
    # hasta el cierre de la ULTIMA. Derivado y no escrito a mano, porque las ventanas
    # salen de los datos y una fecha a mano deja de ser cierta en cuanto el CSV cambia.
    PERIODO_ANALISIS = (f"{VENTANAS[0]['desde'].date()} a "
                        f"{(VENTANAS[-1]['hasta_excl'] - pd.Timedelta(days=1)).date()}")

    PERIODOS = [v['periodo'] for v in VENTANAS]
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
        # DOS filas. El perfil del circuito, que ocupaba una tercera, se fue a su PROPIA
        # figura, debajo del panel y en la columna de la izquierda.
        #
        # Quitar la fila NO basta con borrarla: `row_heights` es una fraccion de lo que
        # sobra DESPUES del espaciado, y el espaciado es a su vez una fraccion del area.
        # Borrar la tercera fila y dejar lo demas igual estiraba las dos de arriba. Los
        # tres numeros se recalculan a la vez a partir de lo MEDIDO con tres filas:
        # fila 1 = 396 px, fila 2 = 311, cada hueco = 96,5, sobre un area de 1.097.
        #
        #     area  = 396 + 311 + 96,5 (un solo hueco ahora) = 803,5
        #     filas = 396/707 y 311/707                      = 0.56 y 0.44
        #     hueco = 96,5 / 803,5                           = 0.12
        # VEINTE columnas y no quince. El perfil del circuito vuelve a la figura, en la fila
        # de abajo y a la izquierda de la evolucion, asi que esa fila pasa de cuatro paneles
        # a CINCO. Con quince no caben: las columnas EN BLANCO entre panel y panel no son
        # decoracion -- son los canales donde cada eje y dibuja sus marcas, y donde el eje
        # DERECHO de la evolucion pone las suyas y su rotulo "Eventos" --, y la cuenta mas
        # apretada que respeta los canales se pasa:
        #
        #     perfil 3 + canal 1 + evolucion 3 + canal 1 + 3 x (panel 2 + canal 1) = 17
        #
        # Con veinte cierra sin dejar a nadie en una sola columna:
        #
        #     fila 1:  nube 9 | canal 2 | mapa 9
        #     fila 2:  perfil 4 | canal 1 | evolucion 5 | canal 1 | 3 x (2 + 1)
        #
        # El reparto sigue siendo proporcional, no en pixeles, y crece con la ventana.
        rows=2, cols=20,
        row_heights=[0.56, 0.44],
        column_widths=[1 / 20] * 20,
        vertical_spacing=0.12, horizontal_spacing=0.012,
        specs=[[{'colspan': 9}, None, None, None, None, None, None, None, None,
                None, None,
                {'type': 'map', 'colspan': 9}, None, None, None, None, None, None, None,
                None],
               [{'colspan': 4}, None, None, None,
                None,
                {'secondary_y': True, 'colspan': 5}, None, None, None, None,
                None,
                {'colspan': 2}, None,
                None,
                {'colspan': 2}, None,
                None,
                {'colspan': 2}, None,
                None]],
        # El orden es por filas sobre las celdas con spec. Los tres de abajo van cortos a
        # proposito: en un sexto del ancho un titulo largo se recorta, y ademas les entra el
        # conteo de muestras que el panel les agrega.
        # El orden es por FILAS sobre las casillas con spec, no por nombre. El perfil entra
        # antes que la evolucion porque va a su izquierda; meterlo al final -- que es donde
        # estaba cuando era una tercera fila -- le pone a cada panel el titulo del vecino
        # sin dar ningun error.
        subplot_titles=('Agrupamiento vano x ventana',
                        'Mapa del circuito -- grupo de cada vano en la ventana',
                        'Perfil del circuito',
                        'Evolucion (llena UITI, punteada eventos)',
                        'Vanos',
                        'UITI',
                        'Eventos'),
    )

    ESCALA_CONTORNO = []
    for g, color in enumerate(COLORES_GRUPOS):
        ESCALA_CONTORNO.append([g / 4.0, color])
        ESCALA_CONTORNO.append([(g + 1) / 4.0, color])

    fig.add_trace(go.Contour(                                        # 0
        z=[[0, 0], [0, 0]], x=[0, 1], y=[0, 1], colorscale=ESCALA_CONTORNO,
        zmin=-0.5, zmax=3.5, showscale=False, opacity=0.28, hoverinfo='skip',
        line=dict(width=1.2, color='rgba(120,20,20,0.6)'),
        contours=dict(start=-0.5, end=3.5, size=1, coloring='fill'), showlegend=False,
    ), row=1, col=1)
    for g in range(4):                                               # 1-4
        fig.add_trace(go.Scattergl(
            x=[], y=[], mode='markers', name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
            marker=dict(size=3.5, color=COLORES_GRUPOS[g], opacity=OPACIDAD_FONDO),
            hovertext=[], hoverinfo='text',
        ), row=1, col=1)

    # Las celdas del circuito elegido viven en sus propias trazas, no en la nube. Es la unica
    # forma de darles opacidad propia sin depender de un `marker.opacity` por punto: la nube
    # entera se atenua al elegir circuito, y estas quedan opacas encima. Cuando ademas hay
    # vanos marcados, estas tambien se atenuan y solo los cupos quedan al frente.
    for g in range(4):                                               # celdas del circuito
        fig.add_trace(go.Scattergl(
            x=[], y=[], mode='markers', name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
            showlegend=False, marker=dict(size=5, color=COLORES_GRUPOS[g], opacity=1.0),
            hovertext=[], hoverinfo='text',
        ), row=1, col=1)

    # Un cupo por vano resaltado. El numero de trazas queda FIJO: marcar o desmarcar solo
    # cambia los datos y el rotulo de cada cupo, nunca cuantas trazas hay. La leyenda sale de
    # estas trazas y, por legendgroup, arrastra a las del mapa y las de la evolucion.
    for s in range(MAX_VANOS_RESALTADOS):                            # cupos de la nube
        fig.add_trace(go.Scattergl(
            x=[], y=[], mode='markers', name='', legendgroup=f'vano{s}', showlegend=False,
            # El RELLENO lo escribe el panel con el color del grupo de cada celda: un vano
            # resaltado cambia de grupo entre ventanas y eso es lo que las flechas cuentan.
            # La identidad del vano se mueve al ANILLO, que si es fija y es la que enlaza este
            # punto con su serie de evolucion y con su linea en el mapa.
            marker=dict(size=10, color=COLOR_CUPO[s],
                        line=dict(width=2.4, color=COLOR_CUPO[s])),
            hovertext=[], hoverinfo='text',
        ), row=1, col=1)
    fig.add_trace(go.Scattergl(                                      # marcados sin cupo
        x=[], y=[], mode='markers', name='Otros elegidos', showlegend=False,
        marker=dict(size=6, color=COLOR_OTROS_ELEGIDOS, opacity=0.85,
                    line=dict(width=0.9, color=COLOR_OTROS_ELEGIDOS)),
        hovertext=[], hoverinfo='text',
    ), row=1, col=1)

    # Evolucion: dos trazas por cupo, UITI a la izquierda y eventos a la derecha. Mismo
    # criterio que 03, con la linea y el punto en codigos distintos: la LINEA lleva el color
    # del cupo y dice de que vano es la serie; el PUNTO lleva el color del grupo de K-Means de
    # esa ventana, con la paleta del agrupamiento. El `x` arranca con las once ventanas y el
    # `y` en null: si arrancara vacio el eje categorico no tendria categorias y la linea del
    # salto de ano caeria en cualquier lado.
    _VACIO = [None] * len(VENTANAS)
    for s in range(MAX_VANOS_RESALTADOS):                            # UITI por cupo
        fig.add_trace(go.Scatter(
            x=PERIODOS_CORTOS, y=list(_VACIO), mode='lines+markers', name='',
            legendgroup=f'vano{s}', showlegend=False,
            line=dict(color=COLOR_CUPO[s], width=2, dash=DASH_CUPO[s]),
            marker=dict(size=[SERIE_TAM_UITI] * len(VENTANAS),
                        color=[COLOR_SIN_GRUPO] * len(VENTANAS),
                        line=dict(width=1.3, color='white')),
            hovertext=[], hoverinfo='text',
        ), row=2, col=6, secondary_y=False)
    for s in range(MAX_VANOS_RESALTADOS):                            # eventos por cupo
        fig.add_trace(go.Scatter(
            x=PERIODOS_CORTOS, y=list(_VACIO), mode='lines+markers', name='',
            legendgroup=f'vano{s}', showlegend=False,
            line=dict(color=COLOR_CUPO[s], width=1.1, dash='dot'),
            marker=dict(size=[SERIE_TAM_EVENTOS] * len(VENTANAS), symbol='square',
                        color=[COLOR_SIN_GRUPO] * len(VENTANAS),
                        line=dict(width=1.2, color='white')),
            hovertext=[], hoverinfo='text',
        ), row=2, col=6, secondary_y=True)

    # El porcentaje va DENTRO de la barra y GIRADO -90 grados, o sea leyendose de abajo hacia
    # arriba: vertical ocupa el ancho de UN renglon en vez del de la cadena entera, que es lo
    # que lo hacia competir por el espacio en un panel de un sexto del ancho. `textangle` SOLO
    # existe en `Bar` -- `Scatter` no lo tiene -- asi que el porcentaje pasa a ser el `text` de
    # la barra y el conteo se muda a la traza de texto. `insidetextanchor='start'` lo ancla al
    # pie de la barra para que crezca hacia arriba desde la base, y `constraintext='none'`
    # evita que Plotly le encoja la letra hasta volverla ilegible: cuando no entra no se
    # achica, se va afuera, y de eso se encarga el umbral del panel.
    fig.add_trace(go.Bar(                                            # barras + porcentaje
        x=NOMBRES_GRUPOS, y=[0] * 4, text=[''] * 4,
        textposition='inside', textangle=-90, insidetextanchor='start',
        constraintext='none',
        insidetextfont=dict(size=11,
                            color=['rgb(40,10,12)', 'rgb(40,10,12)', 'white', 'white']),
        marker=dict(color=COLORES_GRUPOS, line=dict(width=0.5, color='rgba(60,10,10,0.6)')),
        showlegend=False, cliponaxis=False,
        hovertemplate='%{x}: %{y} celdas<extra></extra>',
    ), row=2, col=12)
    # El conteo queda AFUERA, arriba de la barra. Una traza de barras tiene un solo `text` y
    # ese ya lo ocupa el porcentaje, asi que hacen falta dos. Se agrega al final para no
    # correr indices.
    fig.add_trace(go.Scatter(                                        # conteo afuera
        x=NOMBRES_GRUPOS, y=[0] * 4, mode='text', text=[''] * 4,
        textposition='top center',
        textfont=dict(size=11, color='rgb(90,15,20)'),
        showlegend=False, hoverinfo='skip', cliponaxis=False,
    ), row=2, col=12)

    for fila, columna, etiqueta in [(2, 15, 'UITI acumulado'), (2, 18, 'Número de eventos')]:
        for g in range(4):                                           # violines
            fig.add_trace(go.Violin(
                x=[], y=[], name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
                showlegend=False, line=dict(color='rgba(90,15,20,0.85)', width=1),
                fillcolor=COLORES_GRUPOS[g], opacity=0.85,
                box_visible=True, meanline_visible=False, points=False, spanmode='hard',
                hovertemplate=f'%{{x}} -- {etiqueta}: %{{y:,.1f}}<extra></extra>',
            ), row=fila, col=columna)

    # Una traza de mapa por grupo de K-Means, y ya NO vacias: aqui va TODO vano con eventos en
    # la ventana activa, este marcado o no, con el color de su grupo y el ancho de 01.
    #
    # Ese es el defecto que este bloque venia arrastrando. El color grueso era solo para los
    # vanos MARCADOS, asi que desmarcar un vano no le quitaba el resaltado: le borraba el
    # grupo. Volvia a la linea negra de "sin eventos", que es lo contrario de lo que pasa --
    # el vano tuvo eventos, solo que dejo de estar seleccionado. El cuaderno 06 nunca tuvo ese
    # problema porque `capas_mapa_historico` reparte en dos capas distintas, una por clase y
    # otra por marcado, y esto adopta ese mismo reparto.
    for g in range(4):                                               # grupos en el mapa
        fig.add_trace(go.Scattermap(
            lat=[], lon=[], mode='lines', name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
            showlegend=False, line=dict(width=ANCHO_MAPA, color=COLORES_GRUPOS[g]),
            hovertext=[], hoverinfo='text', customdata=[],
        ), row=1, col=12)
    # La estructura del circuito: los vanos SIN eventos en la ventana activa. Antes eran todos,
    # y por eso esta traza se dibujaba encima de las de grupo y las habria tapado. Ahora los
    # dos conjuntos son disjuntos -- con celda arriba, sin celda aqui -- que es el mismo
    # reparto que hace `capas_mapa_historico` en el cuaderno 06.
    # `customdata` lleva el FID de cada punto: es lo que convierte un clic en el mapa en un vano
    # concreto. Resolverlo por indice de punto seria fragil, porque los tramos viajan
    # concatenados con un `None` de separador y ese indice cambia con la ventana.
    fig.add_trace(go.Scattermap(                                     # estructura del circuito
        lat=[], lon=[], mode='lines', name='Sin eventos en la ventana', showlegend=False,
        line=dict(width=ANCHO_SIN_EVENTOS, color=COLOR_SIN_EVENTO),
        hovertext=[], hoverinfo='text', customdata=[],
    ), row=1, col=12)
    # Halo: una sola traza blanca y ancha DEBAJO de los marcados. El ancho de linea sube un
    # 40%, que sobre 3.5 px son 1.4 px de diferencia: medible, pero invisible entre decenas de
    # tramos. El halo despega el vano marcado del resto sin tocar ese ancho, que es la tecnica
    # habitual en cartografia para que una linea salga del fondo.
    fig.add_trace(go.Scattermap(                                     # halo de los marcados
        lat=[], lon=[], mode='lines', name='', showlegend=False,
        line=dict(width=ANCHO_MAPA_RESALTE * 2.6, color='white'), hoverinfo='skip',
    ), row=1, col=12)
    # Los marcados van por encima de los tramos -- pero por DEBAJO de los equipos, que se
    # agregan despues de este bloque -- y repiten grupo por grupo la MISMA paleta que las trazas de arriba: en el mapa el color es siempre el grupo,
    # incluso en lo resaltado. Lo unico que cambia al marcar es el ancho y el halo; el mapa no
    # usa opacidad.
    for g in range(4):                                               # marcados, por grupo
        fig.add_trace(go.Scattermap(
            lat=[], lon=[], mode='lines', name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
            showlegend=False, line=dict(width=ANCHO_MAPA_RESALTE, color=COLORES_GRUPOS[g]),
            hovertext=[], hoverinfo='text', customdata=[],
        ), row=1, col=12)
    # Y el marcado que en esta ventana no tuvo eventos: negro, pero con el ancho del resaltado.
    # No tiene grupo -- eso no es el grupo mas bajo, es la ausencia del dato --, y sin esta
    # traza el halo blanco de 25 px le quedaba encima de una linea de 1,5 y el vano marcado
    # desaparecia en una mancha blanca. Es el `marcados_sin_dato` del cuaderno 06.
    fig.add_trace(go.Scattermap(                                     # marcado sin eventos
        lat=[], lon=[], mode='lines', name='Marcado sin eventos', showlegend=False,
        line=dict(width=ANCHO_MAPA_RESALTE, color=COLOR_SIN_EVENTO),
        hovertext=[], hoverinfo='text', customdata=[],
    ), row=1, col=12)
    # Los equipos van AL FINAL, que es donde los ponen 01 y 03: en MapLibre el orden de las
    # trazas ES el orden de las capas, asi que lo que se agrega despues tapa lo anterior.
    # Antes iban antes del halo y del resaltado, y con el halo en 25 px el mapa perdia equipos:
    # medido sobre el panel exportado del mismo circuito, 19 manchas de transformador contra las
    # 24 de 03, y 5 de interruptor contra 9 -- un 30% y un 60% menos de pixeles de equipo. La
    # marca automatica de la ventana lo agravo, porque ahora casi todo vano con eventos lleva
    # halo. Un transformador tapado no es un detalle de estilo: es el equipo que explica por que
    # ese tramo del circuito se comporta como se comporta.
    # Se renombran las variables del bucle: `_n` y `_c` son las que cuentan las trazas mas abajo
    # para armar `IDX`, y este bucle las pisaba. Solo funcionaba porque el bucle corria antes de
    # `_n = MAX_VANOS_RESALTADOS`; moverlo aqui, sin renombrar, dejaba `_n = 'Switches'`.
    for _nombre_eq, _color_eq, _tam_eq in [('Transformadores', COLOR_TRAFO, TAM_TRAFO),
                                           ('Switches', COLOR_SWITCH, TAM_SWITCH)]:
        fig.add_trace(go.Scattermap(                                 # equipos
            lat=[], lon=[], mode='markers', name=_nombre_eq, showlegend=False,
            marker=dict(size=_tam_eq, color=_color_eq), hovertext=[], hoverinfo='text',
        ), row=1, col=12)

    # --- El perfil del circuito, en la fila de abajo y a la izquierda ---------------
    # Los quince vanos que mas UITI acumulan en TODA la serie, de mayor a menor. Contesta
    # la pregunta con la que se aterriza en un circuito -- donde esta concentrado el
    # riesgo --, que ningun otro panel contesta: la nube, el mapa y la evolucion miran una
    # ventana a la vez.
    #
    # Comparte fila con la evolucion, asi que HEREDA su alto: no hay nada que fijar aqui.
    #
    # Va la ULTIMA de las trazas a proposito. El inventario `IDX` de mas abajo esta escrito
    # como aritmetica sobre el numero de cupos, asi que insertar una traza en medio correria
    # en silencio todo lo que viene despues.
    fig.add_trace(go.Bar(
        x=[], y=[], name='UITI acumulado del periodo', showlegend=False,
        marker=dict(color=COLOR_BARRA_PERFIL,
                    line=dict(width=0.4, color='rgba(60,10,10,0.6)')),
        hovertext=[], hoverinfo='text',
    ), row=2, col=1)
    # `type='category'`: los fid son cadenas de digitos y sin esto plotly los leeria como
    # numeros, con lo que las quince barras se repartirian por su VALOR sobre un eje
    # continuo -- quince postes separados por millones de unidades vacias -- en vez de
    # quedar una al lado de la otra en el orden del ranking.
    # Girados: en cuatro de veinte columnas quince rotulos de ocho digitos no caben de pie.
    fig.update_xaxes(title_text='Vano', type='category', tickfont=dict(size=9),
                     tickangle=-90, row=2, col=1)
    fig.update_yaxes(title_text='UITI acumulado', rangemode='tozero',
                     tickfont=dict(size=9), row=2, col=1)

    # El recuadro vive en el LAYOUT del mapa y no en el inventario de trazas, igual que en el
    # cuaderno 06: `below='traces'` lo deja debajo de todos los tramos, con lo que no intercepta
    # ni el hover ni el clic -- que es justo lo que alterna la seleccion -- y no tapa el color
    # de grupo del vano que esta senialando. Nacen vacias; el panel les escribe el `source` en
    # cada repintado del mapa.
    #
    # CINCO capas y no una: el relleno paso a llevar el color del grupo KMeans del vano, y una
    # entrada de `layout.map.layers` pinta con UN color. Cuatro grupos mas la del marcado que
    # en esta ventana no tiene celda. El ORDEN es fijo y las cinco existen siempre, vacias
    # incluidas, para que el repintado sea una escritura de `source` por capa: quitar y poner
    # capas reordena en MapLibre lo que hay debajo.
    CLASES_CAJA = [0, 1, 2, 3, None]
    COLOR_CAJA_POR_CLASE = COLORES_CAJA_SELECCION + [COLOR_CAJA_SIN_GRUPO]
    CAPAS_CAJA_SELECCION = [
        dict(sourcetype='geojson', type='fill', below='traces',
             source={'type': 'FeatureCollection', 'features': []},
             color=_color, opacity=OPACIDAD_CAJA_SELECCION)
        for _color in COLOR_CAJA_POR_CLASE
    ]

    fig.update_layout(
        map=dict(style='carto-positron', center=dict(lat=5.07, lon=-75.52), zoom=10,
                 layers=CAPAS_CAJA_SELECCION),
        title=dict(text='Agrupamiento y evolucion a nivel de vano con ventana deslizante'
                        '<br><sup>Cada punto es un par vano x ventana; K-Means (k=4) ajustado una '
                        'vez por espacio sobre todas las celdas</sup>',
                   x=0.5, xanchor='center', yref='container', y=0.98, yanchor='top'),
        legend=dict(title_text='', orientation='h', x=0.5, xanchor='center', y=1.008,
                    yanchor='bottom', itemsizing='constant', font=dict(size=11)),
        # Con t=265 quedaban 194 px muertos entre el pie del titulo y la cima de la leyenda,
        # medidos en el navegador. Este valor es solo el punto de partida -- el que sirve
        # cuando la leyenda ocupa un renglon, que es como arranca la figura. A diferencia de
        # 03, aqui la leyenda CRECE al marcar vanos, asi que el panel lo reajusta en el
        # navegador con ajustarMargenSuperior(); ver el comentario de esa funcion.
        margin=dict(t=84, r=MARGEN_DER, b=60, l=MARGEN_IZQ),
        # Sin `width`: la figura la fija el contenedor. Es la condicion para que
        # `default_width='100%'` y `config.responsive` de la celda siguiente surtan efecto y el
        # tablero use todo el ancho de la pantalla en el navegador.
        # 1045: los 803,5 px de area que piden las dos filas mas los margenes REALES.
        # El superior declarado es 84 pero el autoexpand lo lleva a 181 para la leyenda,
        # y es sobre el area resultante -- no sobre la declarada -- donde plotly reparte
        # las filas. Medido: 803,5 + 181 + 60.
        height=1045, template='plotly_white', bargap=0.45, violingap=0.3,
    )
    fig.update_xaxes(title_text='Número de eventos en la ventana', row=1, col=1)
    fig.update_yaxes(title_text='UITI acumulado en la ventana', row=1, col=1)
    # -55 grados y no -30: a 1.280 px el panel de la evolucion mide 396 px para once
    # ventanas, o sea 36 px por marca, y una etiqueta '11-01 a 11-30' de 65 px inclinada 30
    # grados ocupa 56 px de ancho. A 55 grados ocupa 37. Medido: a -30 se pisaban las once.
    # -90 y ya no -55. La evolucion paso de 6 de 15 columnas (40%) a 5 de 20 (25%) al
    # entrar el perfil a su izquierda, o sea un 37% menos de ancho. La cuenta que sostenia
    # los -55 grados se cae con eso: a 1.280 px de ventana eran 36 px por marca y una
    # etiqueta '11-01 a 11-30' inclinada 55 grados ocupa 37 px de ancho -- justo cabia. Con
    # el ancho nuevo quedan ~22 px por marca y las once se volverian a pisar.
    #
    # A 90 grados lo que ocupa la etiqueta ya no es su ancho proyectado sino su ALTURA de
    # linea, unos 12 px, que entra de sobra. Es lo mismo que hace el perfil de al lado con
    # sus quince rotulos.
    fig.update_xaxes(tickangle=-90, tickfont=dict(size=9), row=2, col=6)
    # Los tres paneles de reparto y el eje DERECHO de la evolucion se reparten canales de
    # ~55 px -- eran 98 px cuando la figura ocupaba la pantalla entera. En ese hueco caben
    # las marcas de un panel, el rotulo 'Eventos' y las marcas del vecino solo si la letra
    # baja de la 12 por defecto a la 9, y si el rotulo se pega a sus propias marcas.
    for _col_reparto in (12, 15, 18):
        fig.update_yaxes(tickfont=dict(size=9), row=2, col=_col_reparto)
        fig.update_xaxes(tickfont=dict(size=9), row=2, col=_col_reparto)
    fig.update_yaxes(tickfont=dict(size=9), title_standoff=4,
                     row=2, col=6, secondary_y=True)
    fig.update_yaxes(tickfont=dict(size=9), row=2, col=6, secondary_y=False)
    # Y la fila de arriba, donde la marca '0' del eje x y la mas baja del eje y se tocaban
    # en la esquina: con letra 9 la etiqueta del eje y mide 22 px en vez de 30.
    fig.update_yaxes(tickfont=dict(size=9), row=1, col=1)
    fig.update_xaxes(tickfont=dict(size=9), row=1, col=1)
    fig.update_yaxes(title_text='UITI acumulado', row=2, col=6, secondary_y=False)
    fig.update_yaxes(title_text='Eventos', row=2, col=6, secondary_y=True, showgrid=False)
    # Sin title_text: el titulo del subplot ya nombra el panel y le suma el conteo, y el
    # rotulo del eje solo empujaba las marcas contra el panel vecino.
    fig.update_yaxes(rangemode='tozero', row=2, col=12)
    for _a in fig.layout.annotations:
        _a.font.size = 12





    def _eje(traza, cual):
        ref = getattr(traza, f'{cual}axis') or cual
        return f'{cual}axis' + ref[1:]


    # Los indices se derivan del numero de cupos, no se escriben a mano: con 57 trazas,
    # insertar una sola desplazaria todo lo que viene despues sin avisar. Las aserciones de
    # tipo son la red: si el orden se corre, fallan al generar y no en el navegador.
    _n = MAX_VANOS_RESALTADOS
    _c = 4                                                           # grupos dibujados en el mapa
    IDX = {
        'contorno': 0,
        'nube': [1, 2, 3, 4],
        'circuito': [5, 6, 7, 8],
        'elegidos': list(range(9, 9 + _n)),
        'otros': 9 + _n,
        'serieUiti': list(range(10 + _n, 10 + 2 * _n)),
        'serieEventos': list(range(10 + 2 * _n, 10 + 3 * _n)),
        'barras': 10 + 3 * _n,
        'conteo': 11 + 3 * _n,
        'violinUiti': list(range(12 + 3 * _n, 16 + 3 * _n)),
        'violinEventos': list(range(16 + 3 * _n, 20 + 3 * _n)),
        'mapaGrupos': list(range(20 + 3 * _n, 20 + 3 * _n + _c)),
        'mapaSinEventos': 20 + 3 * _n + _c,
        'mapaHalo': 21 + 3 * _n + _c,
        'mapaResaltado': list(range(22 + 3 * _n + _c, 22 + 3 * _n + 2 * _c)),
        'mapaResaltadoSinDato': 22 + 3 * _n + 2 * _c,
        'mapaTrafos': 23 + 3 * _n + 2 * _c,
        'mapaSwitches': 24 + 3 * _n + 2 * _c,
        'perfil': 25 + 3 * _n + 2 * _c,
    }
    assert len(fig.data) == 26 + 3 * _n + 2 * _c, len(fig.data)
    assert fig.data[IDX['perfil']].type == 'bar'
    assert fig.data[IDX['contorno']].type == 'contour'
    assert fig.data[IDX['barras']].type == 'bar'
    assert fig.data[IDX['conteo']].mode == 'text'
    assert fig.data[IDX['barras']].textangle == -90
    assert all(fig.data[i].type == 'scattergl'
               for i in IDX['nube'] + IDX['circuito'] + IDX['elegidos'] + [IDX['otros']])
    assert all(fig.data[i].type == 'scatter'
               for i in IDX['serieUiti'] + IDX['serieEventos'])
    # `marker.size` de las series tiene que ser un ARRAY: es lo que permite agrandar el punto
    # de la ventana vigente sin partir cada cupo en dos trazas.
    assert all(isinstance(fig.data[i].marker.size, (list, tuple))
               for i in IDX['serieUiti'] + IDX['serieEventos']), (
        'marker.size debe ser un array: el punto de la ventana vigente va al triple')
    assert all(len(fig.data[i].marker.size) == len(VENTANAS)
               for i in IDX['serieUiti'] + IDX['serieEventos'])
    assert all(fig.data[i].type == 'violin'
               for i in IDX['violinUiti'] + IDX['violinEventos'])
    assert all(fig.data[i].type == 'scattermap'
               for i in IDX['mapaGrupos'] + IDX['mapaResaltado'] +
               [IDX['mapaSinEventos'], IDX['mapaResaltadoSinDato'], IDX['mapaTrafos'],
                IDX['mapaSwitches'], IDX['mapaHalo']])
    # El halo tiene que ir DEBAJO de los marcados o los tapa.
    assert IDX['mapaHalo'] < min(IDX['mapaResaltado'] + [IDX['mapaResaltadoSinDato']])
    # El orden de las trazas ES el z-order de las capas de MapLibre. Los equipos van despues de
    # todo lo que dibuja vanos, o el halo de 25 px se los come.
    assert min(IDX['mapaTrafos'], IDX['mapaSwitches']) > IDX['mapaResaltadoSinDato']
    # El perfil es una barra sobre un subplot xy, no una capa del mapa, asi que ir despues
    # de los equipos no los tapa. Lo que la regla persigue son las trazas de MAPA, que son
    # las que MapLibre apila por orden.
    assert all(fig.data[i].type != 'scattermap'
               for i in range(IDX['mapaSwitches'] + 1, len(fig.data))), (
        'ninguna traza de mapa puede ir despues de los equipos: el orden ES el z-order')
    assert IDX['mapaSwitches'] == len(fig.data) - 2, (
        'los equipos son las ULTIMAS trazas de la figura: cualquier traza de mapa agregada '
        'despues los taparia')
    # El recuadro son CINCO capas -- una por grupo mas la del marcado sin celda -- y todas
    # estan debajo de las trazas. Si dejaran de estarlo taparian el color de grupo del vano
    # marcado y se comerian el clic que lo desmarca.
    assert len(fig.layout.map.layers) == len(CLASES_CAJA) == 5
    assert all(_capa.below == 'traces' for _capa in fig.layout.map.layers)
    # El relleno del recuadro y la linea del mismo grupo salen del MISMO color, o el vano queda
    # encerrado en un color y trazado en otro.
    assert ([fig.layout.map.layers[g].color for g in range(4)] ==
            [fig.data[i].line.color for i in IDX['mapaGrupos']] == COLORES_GRUPOS)
    assert fig.layout.map.layers[4].color == COLOR_SIN_GRUPO
    assert all(_capa.opacity == OPACIDAD_CAJA_SELECCION == 0.5
               for _capa in fig.layout.map.layers)
    # Los eventos tienen que haber caido en el eje secundario, no encima del UITI.
    assert (_eje(fig.data[IDX['serieUiti'][0]], 'y')
            != _eje(fig.data[IDX['serieEventos'][0]], 'y'))
    assert all(_eje(fig.data[i], 'y') == _eje(fig.data[IDX['nube'][0]], 'y')
               for i in IDX['circuito'] + IDX['elegidos'] + [IDX['otros']])
    # El mapa comparte la paleta con la nube: es el punto de que un color signifique lo mismo
    # en las dos vistas, asi que si alguien cambia una sola, esto falla al generar.
    assert ([fig.data[i].marker.color for i in IDX['nube']] ==
            [fig.data[i].marker.color for i in IDX['circuito']] ==
            [fig.data[i].line.color for i in IDX['mapaGrupos']] ==
            [fig.data[i].line.color for i in IDX['mapaResaltado']] == COLORES_GRUPOS)
    # Marcar un vano no puede cambiarle el color: el par normal/resaltado coincide tono a tono.
    assert ([fig.data[i].line.color for i in IDX['mapaGrupos']] ==
            [fig.data[i].line.color for i in IDX['mapaResaltado']])
    # El resaltado del mapa tiene que ser exactamente un 40% mas ancho que el trazo normal, y
    # el del marcado sin celda mide lo mismo: lo que cambia al no tener grupo es el COLOR, no
    # el grosor -- si tambien cambiara, marcar un vano sin eventos se leeria como no marcarlo.
    assert all(round(fig.data[i].line.width / ANCHO_MAPA, 3) == 1.4
               for i in IDX['mapaResaltado'] + [IDX['mapaResaltadoSinDato']])
    assert fig.data[IDX['mapaResaltadoSinDato']].line.color == COLOR_SIN_EVENTO
    # Los equipos y la capa de vano, con los tamanos de 01: los cuatro mapas del proyecto
    # dibujan el mismo transformador y el mismo vano del mismo tamano.
    assert (fig.data[IDX['mapaTrafos']].marker.size,
            fig.data[IDX['mapaSwitches']].marker.size) == (TAM_TRAFO, TAM_SWITCH) == (14, 12)
    assert all(fig.data[i].line.width == ANCHO_MAPA == 7.0 for i in IDX['mapaGrupos'])
    assert (fig.data[IDX['mapaSinEventos']].line.width == ANCHO_SIN_EVENTOS
            and fig.data[IDX['mapaSinEventos']].line.color == COLOR_SIN_EVENTO)

    # Salto de ano en la evolucion: los rotulos del eje van sin el ano para que entren, asi
    # que el cambio deja de leerse. El eje es categorico, y la frontera entre la categoria
    # k-1 y la k cae en k - 0.5. Se ancla a mano y no con add_vline(row=, col=): con un
    # subplot de tipo `map` en la figura, add_vline recorre todos los subplots y termina
    # pasandole `xaxis` al Scattermap, que no tiene esa propiedad.
    _evo = fig.data[IDX['serieUiti'][0]]
    _ref_x_evo = 'x' + (_evo.xaxis or 'x')[1:]
    _ref_y_evo = 'y' + (_evo.yaxis or 'y')[1:] + ' domain'
    for _k in range(1, len(VENTANAS)):
        if VENTANAS[_k]['desde'].year != VENTANAS[_k - 1]['desde'].year:
            fig.add_shape(type='line', x0=_k - 0.5, x1=_k - 0.5, y0=0, y1=1,
                          xref=_ref_x_evo, yref=_ref_y_evo,
                          line=dict(dash='dot', width=1.5, color='rgba(60,60,60,0.75)'))
            fig.add_annotation(x=_k - 0.5, y=0.97, xref=_ref_x_evo, yref=_ref_y_evo,
                               text=str(VENTANAS[_k]['desde'].year), showarrow=False,
                               xanchor='right', yanchor='top',
                               font=dict(size=10, color='rgb(60,60,60)'))

    # Titulos que el panel reescribe con el numero de muestras. El indice se resuelve por TEXTO
    # aqui y no a mano: si alguien reordena los subplots el indice sigue siendo el correcto, y si
    # alguien cambia el texto esto falla al generar en vez de reescribir el titulo equivocado.
    TITULOS_N = {}
    for _clave, _texto in [('barras', 'Vanos'),
                           ('violinU', 'UITI'),
                           ('violinN', 'Eventos'),
                           ('perfil', 'Perfil del circuito')]:
        _pos = [i for i, _a in enumerate(fig.layout.annotations) if _a.text == _texto]
        assert len(_pos) == 1, (_texto, _pos)
        TITULOS_N[_clave] = [_pos[0], _texto]

    EJES = {'nubeX': _eje(fig.data[IDX['nube'][0]], 'x'),
            'nubeY': _eje(fig.data[IDX['nube'][0]], 'y'),
            'barras': _eje(fig.data[IDX['barras']], 'y'),
            'violinUiti': _eje(fig.data[IDX['violinUiti'][0]], 'y'),
            'violinEventos': _eje(fig.data[IDX['violinEventos'][0]], 'y')}
    print(f'{len(fig.data)} trazas ({MAX_VANOS_RESALTADOS} cupos de resaltado x 4: nube, '
          f'UITI, eventos y mapa) | ejes: {EJES}')

    DIV = 'vano-ventana'

    # --- El top del PERIODO por circuito ---------------------------------------------------
    # A quien se le marca la casilla sola al ELEGIR CIRCUITO: los vanos que mas UITI acumulan
    # en toda la serie. Es la contraparte de `perfil_uiti_por_vano`
    # (src/chec_local_interpreter/ventanas_015.py), que es lo que el cuaderno 06 usa para lo
    # mismo, y da la misma lista: las quince barras de su panel "Perfil del circuito".
    #
    # Se calcula AQUI, en Python, y no en el navegador como el top de la ventana, porque tiene
    # una sutileza que aquel no tiene: las ventanas SE TRASLAPAN. Cada mes aporta el mes
    # completo y el corte del 15 al 15 hacia el siguiente, asi que casi todo evento cae en dos
    # ventanas y `TABLA` lo trae en dos filas. Sumar las once infla el total de un vano entre
    # 1,00 y 2,09 veces segun el vano, y como el factor no es constante tampoco se cancela al
    # ordenar: 74 de los 208 circuitos cambian su top 15 segun cual de las dos sumas se use.
    #
    # El subconjunto que embaldosa el periodo UNA vez se elige por ENCADENAMIENTO -- se toma la
    # siguiente ventana que empieza donde termino la ultima tomada -- y no por `desde.day == 1`,
    # que es la propiedad que de verdad hace falta: asi el dia del corte puede cambiar arriba
    # sin que esto empiece a contar de mas en silencio. Mismo criterio que `ventanas_sin_traslape`.
    #
    # Este cuaderno NO importa ese modulo a proposito: `ventanas_015` arrastra torch (medido,
    # 1,26 s y 2.590 modulos) y ademas es quien LEE la salida de este cuaderno para extraer la
    # geometria KMeans. Cargarlo aqui ataria el productor de la geometria a su propio
    # consumidor por doce lineas de ranking.
    _SIN_TRASLAPE, _frontera = [], None
    for _v in sorted(VENTANAS, key=lambda v: (v['desde'], v['hasta_excl'])):
        if _frontera is None or _v['desde'] == _frontera:
            _SIN_TRASLAPE.append(_v['i'])
            _frontera = _v['hasta_excl']

    _del_periodo = TABLA[TABLA['ventana_i'].isin(_SIN_TRASLAPE)]
    # Un renglon por vano con las cuatro cifras que el panel del 06 publica en su hover:
    # el total, cuantos eventos son, en cuantas de las ventanas del periodo aparece -- con
    # el mismo total, un vano que fallo una vez y otro que falla mes a mes no son la misma
    # obra -- y que fraccion del UITI del CIRCUITO ENTERO se lleva.
    _totales = (_del_periodo.assign(_fid=_del_periodo['FID_VANO'].astype(str))
                .groupby(['CIRCUITO', '_fid'], as_index=False)
                .agg(uiti_acumulado=('uiti_acumulado', 'sum'),
                     num_eventos=('num_eventos', 'sum'),
                     n_ventanas=('ventana_i', 'nunique')))
    # La participacion se reparte sobre el circuito COMPLETO y antes de recortar al top:
    # sobre los quince dibujados sumaria 1 por construccion y no diria nada.
    _totales['participacion'] = _totales['uiti_acumulado'] / _totales.groupby(
        'CIRCUITO')['uiti_acumulado'].transform('sum').replace(0, pd.NA)
    _totales['participacion'] = _totales['participacion'].fillna(0.0)
    # Empate por fid ascendente: sin desempate el orden lo decidiria el de las filas, y dos
    # tableros sobre el mismo circuito auto-marcarian vanos distintos.
    _totales = _totales.sort_values(['uiti_acumulado', '_fid'], ascending=[False, True])
    TOP_PERIODO_POR_CIRCUITO = {
        str(_c): _g['_fid'].tolist()[:TOP_VANOS_PERIODO]
        for _c, _g in _totales.groupby(_totales['CIRCUITO'].astype(str))
    }
    # El perfil viaja YA recortado y ordenado: son quince barras por circuito, y mandar
    # las 111 mil celdas otra vez para que el navegador rehiciera esta cuenta seria
    # mandar el mismo dato dos veces.
    #
    # `vanos` es el denominador de la frase del titulo -- cuantos vanos del circuito
    # tienen eventos --, y no se puede deducir de las quince barras.
    PERFIL_POR_CIRCUITO = {
        str(_c): {
            'vanos': int(len(_g)),
            'fid': _g['_fid'].tolist()[:TOP_VANOS_PERIODO],
            'uiti': [float(_v) for _v in _g['uiti_acumulado'].tolist()[:TOP_VANOS_PERIODO]],
            'ev': [int(_v) for _v in _g['num_eventos'].tolist()[:TOP_VANOS_PERIODO]],
            'nv': [int(_v) for _v in _g['n_ventanas'].tolist()[:TOP_VANOS_PERIODO]],
            'part': [float(_v) for _v in _g['participacion'].tolist()[:TOP_VANOS_PERIODO]],
        }
        for _c, _g in _totales.groupby(_totales['CIRCUITO'].astype(str))
    }
    print(f'{len(_SIN_TRASLAPE)} de {len(VENTANAS)} ventanas embaldosan el periodo | '
          f'top del periodo precalculado para {len(TOP_PERIODO_POR_CIRCUITO)} circuitos')

    _celdas = TABLA[['FID_VANO', 'ventana_i', 'num_eventos', 'uiti_acumulado']]
    # El circuito viaja por celda como indice, no como cadena: son 111 mil celdas y repetir el
    # nombre en cada una aumentaria el payload sin agregar nada. Sirve para dos cosas: el
    # tooltip lo muestra, y la nube separa las celdas del circuito elegido de las demas.
    _ci_celda = TABLA['CIRCUITO'].astype(str).map({c: i for i, c in enumerate(CIRCUITOS)})
    assert _ci_celda.notna().all(), 'hay celdas con un circuito fuera de CIRCUITOS'
    CONTEXTO = {
        'div': DIV,
        'ventanas': [{'etiqueta': v['etiqueta'], 'periodo': v['periodo']} for v in VENTANAS],
        'periodosCortos': PERIODOS_CORTOS,
        'circuitos': CIRCUITOS,
        'vanosPorCircuito': VANOS_POR_CIRCUITO,
        'espacios': [[bool(a), bool(b), c] for a, b, c in ESPACIOS],
        'grupos': NOMBRES_GRUPOS,
        'colores': COLORES_GRUPOS,
        'colorSinGrupo': COLOR_SIN_GRUPO,
        'geometrias': GEOMETRIAS,
        'extension': EXTENSION,
        'celdas': {'ci': _ci_celda.astype(int).tolist(),
                   'fid': _celdas['FID_VANO'].tolist(),
                   'vi': _celdas['ventana_i'].astype(int).tolist(),
                   'n': _celdas['num_eventos'].astype(int).tolist(),
                   'u': _celdas['uiti_acumulado'].tolist()},
        # UITI_VENTANA no viaja: es la MISMA informacion que 'celdas', indexada de otra forma,
        # y mandar las dos costaba 2.4 MB del cuaderno. El navegador la reconstruye al cargar
        # con un recorrido, que sale en milisegundos.
        'geo': GEO_POR_CIRCUITO, 'trafos': TRAFOS, 'switches': SWITCHES,
        'sinSeleccion': SIN_SELECCION, 'resolucion': 80,
        # `COLOR_CUPO` y no `COLORES_VANOS`: la paleta tiene quince tonos y los cupos son
        # treinta, asi que lo que el panel necesita es la lista YA desplegada. Mandar la corta
        # dejaria sin color a las flechas de la segunda vuelta.
        'maxResaltados': MAX_VANOS_RESALTADOS, 'coloresVanos': COLOR_CUPO,
        'opacidadFoco': OPACIDAD_FOCO, 'opacidadFondo': OPACIDAD_FONDO,
        'serieTamUiti': SERIE_TAM_UITI, 'serieTamEventos': SERIE_TAM_EVENTOS,
        'factorPuntoActivo': FACTOR_PUNTO_ACTIVO,
        'ladoMinimoCaja': LADO_MINIMO_CAJA, 'margenCaja': MARGEN_CAJA,
        # La marca automatica: el top del periodo al elegir circuito -- precalculado arriba --
        # y el de la ventana al mover el deslizador, que el navegador resuelve con las celdas
        # que ya tiene. Los dos topes viajan para que el panel no los escriba a mano.
        'topPeriodo': TOP_PERIODO_POR_CIRCUITO, 'topVentana': TOP_VANOS_VENTANA,
        # El perfil del circuito, ya ordenado y recortado, y cuantas ventanas embaldosan
        # el periodo -- que es el denominador del "en 2 de 6 ventanas" de su hover.
        'perfil': PERFIL_POR_CIRCUITO, 'ventanasDelPeriodo': len(_SIN_TRASLAPE),
    }

    # El primer circuito viene elegido de fabrica (paridad con el cuaderno 03). La opcion
    # `(ninguno)` se conserva -- es la vista de toda la nube, sin circuito de interes -- pero
    # ya no es el arranque: abrir el tablero en un estado que no muestra ningun mapa obliga a
    # elegir algo antes de ver nada, y el primer circuito es una eleccion tan buena como
    # cualquiera para empezar a mirar.
    _opts = ''.join(f'<option value="{c}"{" selected" if i == 0 else ""}>{c}</option>'
                    for i, c in enumerate(CIRCUITOS))
    _escala = '<span style="display:inline-flex;gap:2px;align-items:center;">' + ''.join(
        f'<span style="display:inline-block;width:20px;height:10px;background:{c};"></span>'
        f'<span style="font-size:10px;color:#747378;margin-right:8px;">{n}</span>'
        for n, c in zip(NOMBRES_GRUPOS, COLORES_GRUPOS)) + '</span>'
    # La barra del panel se queda solo con la escala del mapa. Lo que hace la seleccion --
    # color propio, leyenda, halo, trazo mas ancho, el tope de ocho -- se lee en la leyenda de
    # la figura y en el aviso, que ademas dicen los nombres y las cifras del momento; repetirlo
    # aqui era una glosa fija que ocupaba dos renglones y no se actualizaba con nada.

    PANEL_HTML = f'''
<style>
  .panel-v4 {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 13px;
    display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end;
    /* El panel sigue el ancho de la figura, que ya no es fijo: la figura se genera sin
       `width` y con `default_width='100%'`, de modo que ocupa el ancho disponible.
       `border-box` mantiene relleno y bordes DENTRO de ese ancho y no encima. */
    width: 100%; box-sizing: border-box;
    margin: 0 0 6px 0; padding: 12px 14px;
    border: 1px solid #cfe3ac; border-left: 4px solid rgb(0,128,36);
    border-radius: 6px; background: #f3f8ec; color: #2b2b2b;
  }}
  .panel-v4 label {{ display: block; font-weight: 600; margin-bottom: 4px; }}
  .panel-v4 select {{ font: inherit; padding: 4px 6px; border: 1px solid #a8c97a;
    border-radius: 4px; background: #fff; min-width: 140px; }}
  .panel-v4 .chk {{ font-weight: 600; display: flex; align-items: center; gap: 6px; }}
  .panel-v4 .col {{ display: flex; flex-direction: column; gap: 6px; }}
  .panel-v4 button {{ font: inherit; font-weight: 600; padding: 5px 10px; cursor: pointer;
    border: 1px solid rgb(0,128,36); border-radius: 4px; background: rgb(0,128,36);
    color: #fff; }}
  .panel-v4 .lista {{ flex-basis: 100%; max-height: 132px; overflow-y: auto;
    border: 1px solid #cfe3ac; border-radius: 4px; background: #fff; padding: 6px 8px;
    display: flex; flex-wrap: wrap; gap: 2px 14px; font-size: 12px; }}
  .panel-v4 .lista label {{ font-weight: 400; margin: 0; display: flex; gap: 5px;
    align-items: center; white-space: nowrap; }}
  .panel-aviso {{ flex-basis: 100%; font-size: 12px; color: #747378; margin: 0; }}
</style>
<div class="panel-v4">
  <div><label for="v4-circuito">Circuito</label>
       <select id="v4-circuito">
         <option value="{SIN_SELECCION}">{SIN_SELECCION}</option>{_opts}
       </select></div>
  <div class="col">
    <button type="button" id="v4-todos">Marcar todos</button>
    <button type="button" id="v4-ninguno">Desmarcar</button>
  </div>
  <div style="flex:1; min-width:240px;">
    <label for="v4-ventana">Ventana</label>
    <div style="display:flex; align-items:center; gap:8px;">
      <input type="range" id="v4-ventana" min="0" max="{len(VENTANAS) - 1}" value="0" step="1"
             style="flex:1; accent-color: rgb(139,194,27);">
      <span id="v4-ventana-txt" style="font-weight:600; white-space:nowrap;
            min-width:190px;"></span>
    </div>
  </div>
  <div class="lista" id="v4-vanos"><em style="color:#747378;">Seleccione un circuito para listar sus vanos.</em></div>
  <div style="flex-basis:100%; font-size:11.5px; color:#5b4a48; margin-top:-2px;">
    Lista de vanos con eventos del circuito en el periodo: <b>{PERIODO_ANALISIS}</b>
  </div>
  <div style="flex-basis:100%; font-size:11.5px; display:flex; flex-wrap:wrap; gap:4px 14px;
              align-items:center; color:#5b4a48;">
    <span style="font-weight:600;">Mapa:</span>
    <span>grupo del vano en la ventana</span>{_escala}
    <span><span style="display:inline-block;width:20px;height:0;border-top:3px solid
      {COLOR_SIN_EVENTO};vertical-align:middle;margin-right:5px;"></span>Sin eventos</span>
    <span><span style="display:inline-block;width:18px;height:18px;background:{COLOR_TRAFO};
      border-radius:50%;margin-right:5px;"></span>Transformador</span>
    <span><span style="display:inline-block;width:18px;height:18px;background:{COLOR_SWITCH};
      border-radius:50%;margin-right:5px;"></span>Interruptor</span>
  </div>
  <p class="panel-aviso" id="v4-aviso"></p>
</div>
'''

    PANEL_JS = '''
<script type="text/javascript">
(function () {
  var CTX = %s;
  var d = document;
  var ULTIMO_CIRCUITO = null, ULTIMO_CENTRADO = null;
  // La caja amarilla se redibuja con un relayout, que es caro: la firma evita pagarlo
  // mientras la seleccion no cambie (arrastrar el deslizador sobre los mismos vanos).
  var ULTIMA_CAJA = null;
  // El espacio y el foco se recuerdan para no rehacer lo que no cambio: violines, barras y
  // contorno solo dependen del espacio (log y preproceso), no de que circuito o que vanos
  // se elijan. Cada restyle que cambia algo cuesta un redibujado completo de la figura, asi
  // que saltarse los innecesarios vale mas que abaratar los datos que se mandan.
  var ULTIMO_ESPACIO = null, ULTIMO_FOCO = null;
  var MAX_CUENTA = 1;
  // Lo ultimo que se dibujo, para no volver a dibujarlo igual. El manejador del
  // deslizador pinta el mapa y el punto activo de inmediato -- para que sigan al
  // dedo -- y `aplicar()` corria 140 ms despues y los repetia con los MISMOS
  // argumentos: 234 ms por paso de ventana sin que cambiara un pixel, medido en
  // Chrome. Con 111.000 celdas en la nube, cada llamada a Plotly cuesta 130 ms
  // aunque no toque la nube -- recalcula la figura entera --, asi que lo que se
  // persigue es el NUMERO de llamadas, no lo que llevan dentro.
  var FIRMA_MAPA = null, VENTANA_PINTADA = null;

  function ventanaActual() {
    var el = d.getElementById('v4-ventana');
    return el ? (parseInt(el.value, 10) || 0) : 0;
  }

  // Agrega `origen` al final de `destino` SIN crear un arreglo nuevo. `concat` crea uno en
  // cada llamada, y el mapa reparte ahora los vanos en cinco destinos en vez de dos: sobre
  // los cientos de tramos de un circuito grande, eso es copiar la lista entera una vez por
  // vano y por destino. `apply` tiene un tope de argumentos por llamada, y aqui no lo roza:
  // un vano densificado son 600 puntos como mucho (`MAX_CORTES_TRAMO`).
  function empujar(destino, origen) {
    Array.prototype.push.apply(destino, origen);
  }

  function limEje(lo, hi, log) {
    // En log Plotly espera el rango YA en log10; el piso evita un log10(0).
    return log ? [Math.log10(Math.max(lo, 1e-6) * 0.85), Math.log10(hi * 1.15)]
               : [0, hi * 1.05];
  }

  // Violines, barras y porcentajes describen SOLO la ventana elegida Y SOLO los vanos que
  // quedaron al frente, en la misma cascada que gobierna las opacidades: si hay vanos
  // marcados son esos, si no los del circuito elegido, y sin circuito toda la nube. La
  // nube de fondo si lleva todas las ventanas -- es la trayectoria completa y filtrarla
  // dejaria sin sentido las flechas entre ventanas consecutivas -- asi que el reparto
  // describe lo que esta al frente, no todo lo dibujado.
  // El perfil del circuito: los quince vanos que mas UITI acumulan en TODA la serie.
  //
  // Depende SOLO del circuito -- ni de la ventana ni de lo que este marcado --, asi
  // que se pinta una vez por cambio de circuito y no en cada paso del deslizador ni
  // en cada casilla. Es deliberado, y es la misma decision del cuaderno 06: el panel
  // esta para leerse ANTES de tomar esas dos decisiones, y repintarlo con ellas lo
  // convertiria en otro panel de seleccion, que ya hay cuatro. Ademas lo dejaria en
  // el camino del deslizador, que es justo el que se acaba de aligerar.
  //
  // Devuelve el cambio de titulo para que lo mande el relayout de aplicar(), por el
  // mismo motivo que el reparto: cada llamada a Plotly cuesta un redibujado entero.
  //
  // Devuelve el cambio de titulo para que lo mande el relayout de aplicar(), por el mismo
  // motivo que el reparto: cada llamada a Plotly cuesta un redibujado entero.
  function pintarPerfil(gd, circuito) {
    var p = CTX.perfil[circuito];
    if (!p || !p.fid.length) {
      Plotly.restyle(gd, {x: [[]], y: [[]], hovertext: [[]]}, [CTX.idx.perfil]);
      // En DOS lineas y la segunda en `<sup>`: el panel ocupa 4 de 20 columnas -- unos
      // 220 px medidos --, y de una sola linea el titulo se salia por los dos lados y se
      // montaba sobre el de la evolucion, que es su vecino. Una anotacion de subplot no
      // parte sola; el `<br>` es la unica forma.
      return 'Perfil del circuito<br><sup>sin eventos en el periodo</sup>';
    }
    var txt = [], concentracion = 0;
    for (var i = 0; i < p.fid.length; i++) {
      concentracion += p.part[i];
      txt.push('<b>Vano ' + p.fid[i] + '</b><br>UITI acumulado del periodo: ' +
               p.uiti[i].toLocaleString('es-CO', {maximumFractionDigits: 1}) +
               '<br>' + p.ev[i].toLocaleString('es-CO') + ' evento(s) en ' + p.nv[i] +
               ' de ' + CTX.ventanasDelPeriodo + ' ventanas<br>' +
               (100 * p.part[i]).toFixed(1) + '%% del UITI del circuito');
    }
    Plotly.restyle(gd, {x: [p.fid], y: [p.uiti], hovertext: [txt]},
                   [CTX.idx.perfil]);
    // El denominador son TODOS los vanos del circuito con eventos, no los quince
    // dibujados: la frase dice cuanto del circuito cabe en el panel, y sobre los dibujados
    // diria siempre el 100%%. Redactada corta porque el panel es estrecho.
    return 'Perfil del circuito<br><sup>' + p.fid.length + ' de ' + p.vanos +
           ' vanos: ' + (100 * concentracion).toFixed(1) + '%% del UITI</sup>';
  }

  function dibujarReparto(gd, act, circuito, cu) {
    var w = ventanaActual(), C = CTX.celdas, geo = act.geo, i, g;
    // El unico sujeto son los vanos MARCADOS. Sin marcas no hay reparto que describir:
    // barras y violines quedan vacios en vez de caer al circuito entero o a la nube. Un
    // reparto de 27.390 vanos y otro de tres se dibujan igual pero no dicen lo mismo, y
    // sin nada que los distinga se leen como si fueran la misma medida.
    var marcados = {};
    for (i = 0; i < cu.lista.length; i++) { marcados[cu.lista[i]] = true; }
    var hayMarcados = cu.lista.length > 0;

    var vg = [[], [], [], []], mx = [[], [], [], []], my = [[], [], [], []];
    var porVentana = [];
    for (i = 0; i < CTX.ventanas.length; i++) { porVentana.push([0, 0, 0, 0]); }
    // Extremos del conjunto elegido sobre TODAS sus ventanas: son los que fijan la escala
    // de los violines. Usar la extension global dejaria una seleccion de tres vanos
    // aplastada contra el piso del eje.
    var minN = Infinity, maxN = -Infinity, minU = Infinity, maxU = -Infinity;
    for (i = 0; hayMarcados && i < C.fid.length; i++) {
      if (marcados[C.fid[i]] !== true) { continue; }
      g = grupoDe(C.n[i], C.u[i], geo);
      porVentana[C.vi[i]][g] += 1;
      if (C.n[i] < minN) { minN = C.n[i]; }
      if (C.n[i] > maxN) { maxN = C.n[i]; }
      if (C.u[i] < minU) { minU = C.u[i]; }
      if (C.u[i] > maxU) { maxU = C.u[i]; }
      if (C.vi[i] !== w) { continue; }
      vg[g].push(CTX.grupos[g]); mx[g].push(C.n[i]); my[g].push(C.u[i]);
    }
    if (!isFinite(minN)) { minN = CTX.extension[0]; maxN = CTX.extension[1]; }
    if (!isFinite(minU)) { minU = CTX.extension[2]; maxU = CTX.extension[3]; }

    var cuenta = porVentana[w] || [0, 0, 0, 0], maxGlobal = 1;
    for (i = 0; i < porVentana.length; i++) {
      for (g = 0; g < 4; g++) {
        if (porVentana[i][g] > maxGlobal) { maxGlobal = porVentana[i][g]; }
      }
    }
    MAX_CUENTA = maxGlobal;

    // El porcentaje se calcula sobre las celdas de ESTA ventana, para que las cuatro
    // cifras sumen 100. Dentro de la barra solo si hay altura; si no, pegado al conteo de
    // afuera, o el texto de media altura caeria sobre el eje encimandose con el nombre
    // del grupo.
    var tot = cuenta[0] + cuenta[1] + cuenta[2] + cuenta[3];
    var pctTxt = cuenta.map(function (c) {
      // Simbolo duplicado: este bloque se arma con formateo de cadena.
      return tot ? (100 * c / tot).toFixed(1) + '%%' : '';
    });
    // Girado, el porcentaje necesita ALTO donde antes necesitaba ancho: "40.6%%" vertical
    // mide unos 40 px contra los 13 de un renglon horizontal. Por eso el umbral bajo el
    // cual no entra en la barra sube de 0.12 a 0.22 del maximo. Debajo de eso el
    // porcentaje se va afuera pegado al conteo, igual que antes.
    var bajo = cuenta.map(function (c) { return c / maxGlobal < 0.22; });
    var pct = pctTxt.map(function (p, j) { return (bajo[j] || !cuenta[j]) ? '' : p; });
    // Un grupo vacio no se rotula. Sin marcas eso deja el panel en blanco y el aviso
    // explica por que; con una seleccion pequena evita que tres ceros con su porcentaje
    // compitan con el unico grupo que si tiene celdas.
    var conteoTxt = cuenta.map(function (c, j) {
      return (!tot || !c) ? '' : (bajo[j] ? c + '  ' + pctTxt[j] : String(c));
    });
    var sinTexto = [];
    for (i = 0; i < 8; i++) { sinTexto.push([]); }
    Plotly.restyle(gd, {
      x: vg.concat(vg, [CTX.grupos, CTX.grupos]),
      y: my.concat(mx, [cuenta, cuenta]),
      text: sinTexto.concat([pct, conteoTxt]),
    }, CTX.idx.violinUiti.concat(CTX.idx.violinEventos,
                                 [CTX.idx.barras, CTX.idx.conteo]));

    // Escalas fijas sobre TODAS las ventanas del conjunto elegido: con autorango, una
    // ventana con la mitad de celdas se veria igual de alta y mover el slider no contaria
    // nada. Cada violin sigue la extension de SU propia variable, no la del eje en que
    // esta dibujado.
    var ejes = {};
    ejes[CTX.ejes.barras + '.range'] = [0, maxGlobal * 1.18];
    ejes[CTX.ejes.violinUiti + '.range'] = limEje(minU, maxU, act.logy);
    ejes[CTX.ejes.violinEventos + '.range'] = limEje(minN, maxN, act.logx);
    // Los titulos dicen cuantas muestras resumen: sin eso, dos ventanas con reparto
    // parecido se leen igual aunque una tenga la mitad de vanos marcados. Van por INDICE y
    // en el mismo relayout que los rangos, para no pisar las flechas, que viven en el mismo
    // array de anotaciones. El snapshot guarda las MISMAS referencias que gd.layout, asi
    // que actualizarlo evita que el relayout completo de aplicar() revierta el titulo.
    // El titulo NO viaja como `annotations[i].text` porque el unico que llama aqui es
    // `aplicar()`, que en la misma pasada reescribe el array `annotations` entero -- y lo
    // hace con estas mismas referencias, porque `fig_anotaciones` es una copia
    // superficial de `gd.layout.annotations`. Mutar el objeto basta, y mezclar en un solo
    // relayout la escritura del array y la de un indice suyo es justo la forma de que uno
    // pise al otro.
    var claves = ['barras', 'violinU', 'violinN'];
    for (i = 0; i < claves.length; i++) {
      var par = CTX.titulos[claves[i]], titulo = par[1] + ' (n = ' + tot + ')';
      if (fig_anotaciones && fig_anotaciones[par[0]]) { fig_anotaciones[par[0]].text = titulo; }
    }
    // Se devuelven en vez de aplicarse: eran un `relayout` propio de 125 ms pegado al de
    // `aplicar()`, de 116 ms, y los dos juntos cuestan lo que uno solo.
    return ejes;
  }

  // El reparto depende del espacio, la ventana, el circuito y los vanos marcados. La firma
  // evita rehacerlo cuando nada de eso cambio: es el restyle mas caro de la figura.
  var ULTIMA_FIRMA = null;

  // Devuelve los cambios de layout del reparto para que `aplicar()` los funda con
  // los suyos: eran dos `relayout` seguidos de 125 y 116 ms, y juntos cuestan lo
  // que uno. Cuando la firma no cambio no hay nada que fundir.
  function refrescarReparto(gd, act, circuito, cu) {
    var firma = act.i + '|' + ventanaActual() + '|' + circuito + '|' + cu.lista.join(',');
    if (firma === ULTIMA_FIRMA) { return {}; }
    ULTIMA_FIRMA = firma;
    return dibujarReparto(gd, act, circuito, cu);
  }

  // Ventana de cada punto dibujado, por bucket, para que mover el slider solo repinte
  // opacidades en vez de rehacer la nube entera.
  var VENT_NUBE = [[], [], [], []], VENT_CIRC = [[], [], [], []];
  var VENT_CUPO = [], VENT_OTROS = [], SIN_CIRCUITO = true;

  // `delCircuito` dice si ese bucket pertenece al circuito de interes. Los tres buckets
  // que si -- celdas del circuito, cupos y otros elegidos -- se construyen filtrando por
  // el circuito activo, asi que ahi la pregunta ya esta contestada y solo queda la
  // ventana. El bucket de la nube son los OTROS circuitos y nunca entra al foco, salvo
  // cuando no hay circuito elegido: ahi todo cae en la nube y manda la ventana sola.
  function opsDe(ventanas, w, delCircuito) {
    var arr = [];
    for (var i = 0; i < ventanas.length; i++) {
      arr.push((delCircuito && ventanas[i] === w) ? CTX.opacidadFoco : CTX.opacidadFondo);
    }
    return arr;
  }

  // Opacidad POR PUNTO: solo las celdas del circuito de interes EN la ventana de interes
  // van opacas; todo lo demas queda de fondo. Los vanos marcados siguen distinguiendose
  // por tamano y por su anillo de color, que es lo que dice de que vano son -- la
  // opacidad ya no tiene que cargar tambien con esa distincion.
  function opacidadesActuales() {
    var w = ventanaActual(), i, g, ops = [];
    for (g = 0; g < 4; g++) { ops.push(opsDe(VENT_NUBE[g], w, SIN_CIRCUITO)); }
    for (g = 0; g < 4; g++) { ops.push(opsDe(VENT_CIRC[g], w, true)); }
    for (i = 0; i < CTX.maxResaltados; i++) {
      ops.push(opsDe(VENT_CUPO[i] || [], w, true));
    }
    ops.push(opsDe(VENT_OTROS, w, true));
    return ops;
  }

  function pintarOpacidades(gd) {
    Plotly.restyle(gd, {'marker.opacity': opacidadesActuales()},
      CTX.idx.nube.concat(CTX.idx.circuito, CTX.idx.elegidos, [CTX.idx.otros]));
  }

  // El punto de la ventana vigente en las series de evolucion, al triple. Mismo recurso
  // que la serie del cuaderno 01: `marker.size` es un arreglo y aqui solo se reescribe,
  // sin tocar ni los datos ni el color de los marcadores. Todos los cupos comparten el
  // mismo arreglo -- todos tienen las mismas once ventanas en el mismo orden.
  // Va SEPARADO de `pintarOpacidades` a proposito: esto es barato y corre en vivo en cada
  // paso del arrastre, mientras que repintar la opacidad de 110 mil celdas va con retardo.
  // Reescribe `marker.size` de 60 trazas -- 127 ms medidos -- y lo que dibuja
  // depende SOLO de cual es la ventana activa. Repetirlo en la misma ventana no
  // puede cambiar nada, y se repetia una vez por paso.
  function pintarPuntoActivo(gd) {
    var w = ventanaActual(), i;
    if (w === VENTANA_PINTADA) { return; }
    VENTANA_PINTADA = w;
    function tam(base) {
      return CTX.ventanas.map(function (_, k) {
        return k === w ? base * CTX.factorPuntoActivo : base;
      });
    }
    var tu = [], tn = [], su = tam(CTX.serieTamUiti), sn = tam(CTX.serieTamEventos);
    for (i = 0; i < CTX.maxResaltados; i++) { tu.push(su); tn.push(sn); }
    Plotly.restyle(gd, {'marker.size': tu.concat(tn)},
                   CTX.idx.serieUiti.concat(CTX.idx.serieEventos));
  }

  // El titulo cuelga del tope de la figura, pero la leyenda horizontal crece HACIA ARRIBA
  // desde el borde del area de dibujo, y su alto depende de cuantos vanos esten marcados:
  // con los cuatro grupos ocupa un renglon (29 px) y con ocho vanos ocupa dos (58 px). Un
  // margen superior fijo solo puede elegir entre dejar un hueco muerto bajo el titulo o
  // dejar que la leyenda se le monte encima. En vez de clavar un numero se miden las dos
  // cajas ya dibujadas y se corre el margen exactamente la diferencia.
  var HOLGURA_TITULO = 12;   // px libres entre el pie del titulo y la cima de la leyenda

  function ajustarMargenSuperior(gd, pasadas) {
    if (!gd || !gd._fullLayout) { return; }
    var titulo = gd.querySelector('.g-gtitle'), leyenda = gd.querySelector('g.legend');
    if (!titulo || !leyenda) { return; }
    var marco = gd.getBoundingClientRect();
    var pie = titulo.getBoundingClientRect().bottom - marco.top;
    var cima = leyenda.getBoundingClientRect().top - marco.top;
    var actual = gd._fullLayout.margin.t;
    var pedido = Math.round(actual + pie + HOLGURA_TITULO - cima);
    // Umbral de 2 px: cada relayout cambia el alto del area de dibujo, y la leyenda esta
    // anclada a una FRACCION de ese alto, asi que despues del ajuste se corre un poco mas.
    // Sin el umbral el ajuste se perseguiria a si mismo en cada pasada.
    if (Math.abs(pedido - actual) < 2) { return; }
    Plotly.relayout(gd, {'margin.t': Math.max(pedido, 40)}).then(function () {
      // Una sola pasada no converge, y con la figura al 70%% dejo de bastar: la leyenda
      // esta anclada a una FRACCION del alto del area de dibujo, asi que al mover el
      // margen se mueve con el. Medido a 1.280 px con la leyenda en cinco renglones, la
      // primera pasada se quedaba corta y el titulo seguia pisado. El umbral de 2 px de
      // arriba corta la recursion en cuanto converge; el tope de tres es el cinturon.
      if ((pasadas || 0) < 3) { ajustarMargenSuperior(gd, (pasadas || 0) + 1); }
    });
  }

  // uitiVentana[w][fid] = [uiti, eventos], derivada de las celdas en vez de viajar aparte.
  var UITI_VENTANA = (function () {
    var out = [], C = CTX.celdas, i;
    for (i = 0; i < CTX.ventanas.length; i++) { out.push({}); }
    for (i = 0; i < C.fid.length; i++) { out[C.vi[i]][C.fid[i]] = [C.u[i], C.n[i]]; }
    return out;
  })();

  function elegidos() {
    var out = {}, cajas = d.querySelectorAll('#v4-vanos input[type=checkbox]');
    for (var i = 0; i < cajas.length; i++) {
      if (cajas[i].checked) { out[cajas[i].value] = true; }
    }
    return out;
  }

  // Reparte los marcados en cupos. El orden es el de la lista, asi que el color de un
  // vano no cambia mientras no se toquen los que estan antes que el.
  function cuposDe(sel) {
    var lista = Object.keys(sel), cupos = lista.slice(0, CTX.maxResaltados), de = {};
    for (var i = 0; i < cupos.length; i++) { de[cupos[i]] = i; }
    return {lista: lista, cupos: cupos, de: de};
  }

  function poblarLista(circuito) {
    var caja = d.getElementById('v4-vanos');
    var vanos = CTX.vanosPorCircuito[circuito] || [];
    if (!vanos.length) {
      caja.innerHTML = '<em style="color:#747378;">Seleccione un circuito para listar sus vanos.</em>';
      return;
    }
    var html = '';
    for (var i = 0; i < vanos.length; i++) {
      html += '<label><input type="checkbox" value="' + vanos[i] + '">' + vanos[i] + '</label>';
    }
    caja.innerHTML = html;
    caja.querySelectorAll('input[type=checkbox]').forEach(function (c) {
      c.addEventListener('change', aplicar);
    });
  }

  // El espacio es unico y fijo -- eje x lineal, eje y logaritmico, minmax -- y ya no hay
  // controles que lo cambien. El mapa lo necesita tanto como la nube, porque el color de un
  // vano es su grupo. Se lee de `CTX.espacios` y no de dos constantes escritas aqui, para
  // que el dibujo no pueda contradecir a la geometria con que se ajusto K-Means en Python.
  // Sigue devolviendo `i` porque `cambioEspacio` lo usa para hacer la grilla del contorno
  // una sola vez: con un espacio fijo, esa comparacion solo es cierta en la primera pasada.
  function geoActual() {
    var esp = CTX.espacios[0];
    return {i: 0, logx: esp[0], logy: esp[1], geo: CTX.geometrias['0']};
  }

  function grupoDe(nx, uy, geo) {
    var vx = geo.logs[0] ? Math.log10(nx) : nx, vy = geo.logs[1] ? Math.log10(uy) : uy;
    var tx = (vx - geo.offset[0]) / geo.scale[0], ty = (vy - geo.offset[1]) / geo.scale[1];
    var mejor = 0, dmin = Infinity;
    for (var c = 0; c < geo.centroides.length; c++) {
      var a = tx - geo.centroides[c][0], b = ty - geo.centroides[c][1], dd = a * a + b * b;
      if (dd < dmin) { dmin = dd; mejor = c; }
    }
    return mejor;
  }

  function ejeGrilla(min, max, n, log) {
    var out = [], lo = log ? Math.log10(min) : min, hi = log ? Math.log10(max) : max;
    var paso = (hi - lo) / (n - 1);
    for (var i = 0; i < n; i++) {
      var v = lo + i * paso;
      out.push(log ? Math.pow(10, v) : v);
    }
    return out;
  }

  // Marcar y desmarcar un vano tocandolo en el mapa. Es el mismo estado que las casillas:
  // el clic no lleva un registro paralelo, alterna la casilla y deja que aplicar() rehaga
  // todo. Asi la lista, el mapa, la nube y el reparto no pueden contar cosas distintas.
  var CLIC_LISTO = false;

  function marcarPorFid(fid) {
    var cajas = d.querySelectorAll('#v4-vanos input[type=checkbox]');
    for (var i = 0; i < cajas.length; i++) {
      if (cajas[i].value === String(fid)) {
        cajas[i].checked = !cajas[i].checked;
        // Traerla a la vista: con circuitos de cientos de vanos, la casilla que acaba de
        // cambiar suele estar fuera del scroll de la lista.
        if (cajas[i].scrollIntoView) {
          cajas[i].scrollIntoView({block: 'nearest'});
        }
        aplicar();
        return true;
      }
    }
    return false;
  }

  // --- El recuadro amarillo del vano marcado ---------------------------------------
  // Puerto a JS de `cajas_seleccion` (src/chec_local_interpreter/ventanas_015.py), que es
  // lo que el cuaderno 06 pinta sobre su mapa historico. Se porta y no se aproxima: el
  // mismo rectangulo, con los mismos dos parametros, para que el resaltado mida lo mismo
  // en los dos tableros.
  //
  // El rectangulo sigue la INCLINACION del vano y no los ejes norte-sur. Lo que eso corrige
  // es el GROSOR del resaltado: la caja min/max de un tramo diagonal sobresale por las dos
  // esquinas que la linea nunca toca, y cuanto sobresale depende del rumbo y del largo del
  // vano -- medido sobre los 59.776 tramos, la caja alineada a los ejes es 1,3 veces mas
  // ancha que la banda que cruza al tramo en la mediana, 4 veces en el p90 y 169 en el peor
  // caso. Girada al rumbo del vano el ancho es `ladoMinimoCaja + 2 * margenCaja` en todos.
  //
  // Sale de la GEOMETRIA y no de las celdas de la ventana: por eso el recuadro sigue puesto
  // al mover el deslizador, incluso sobre un vano que en esa ventana no tuvo ni un evento.
  // Se apaga solo al desmarcar -- por su casilla o volviendo a tocarlo en el mapa.
  // `clasePorFid` reparte los rectangulos en CINCO colecciones -- una por grupo KMeans mas
  // la del marcado que en esta ventana no tiene celda --, porque una capa de
  // `layout.map.layers` pinta con UN color y el relleno paso a llevar el color del grupo.
  // Es el mismo reparto que hace `cajas_seleccion_por_clase` en el cuaderno 06.
  function cajasSeleccion(circuito, sel, clasePorFid) {
    var info = (circuito !== CTX.sinSeleccion) ? CTX.geo[circuito] : null;
    var porClase = [], i, k;
    for (i = 0; i < 5; i++) { porClase.push([]); }
    // Se recorren los vanos de ESTE circuito: un fid marcado que no tiene coordenadas aqui
    // no produce ninguna caja, en vez de dejar un rectangulo fantasma del circuito anterior.
    for (i = 0; info && i < info.fids.length; i++) {
      var fid = info.fids[i];
      if (sel[fid] !== true) { continue; }
      // Sin clase en esta ventana va a la QUINTA capa, la gris. No tiene grupo, y eso no
      // es el grupo mas bajo: es la ausencia del dato.
      var capa = (clasePorFid[fid] === undefined || clasePorFid[fid] < 0)
                 ? 4 : clasePorFid[fid];
      var la = info.lat[i], lo = info.lon[i];
      if (!la || !la.length) { continue; }
      var dLo = lo[lo.length - 1] - lo[0], dLa = la[la.length - 1] - la[0];
      var largo = Math.sqrt(dLo * dLo + dLa * dLa);
      // `u` corre CON el vano y `v` lo cruza; `v` es `u` girado 90 grados en sentido
      // antihorario, que es el sentido que GeoJSON pide para el anillo exterior. Los tramos
      // cuyos dos vertices son el MISMO punto no tienen rumbo, y ahi se cae al rectangulo
      // alineado a los ejes: es el unico rectangulo honesto sobre un vano que no apunta a
      // ningun lado.
      var u = largo ? [dLo / largo, dLa / largo] : [1, 0];
      var v = [-u[1], u[0]];
      // Cada vertice, medido a lo largo (`s`) y a traves (`t`) del vano.
      var s = [], t = [];
      for (k = 0; k < la.length; k++) {
        var p = lo[k] - lo[0], q = la[k] - la[0];
        s.push(p * u[0] + q * u[1]);
        t.push(p * v[0] + q * v[1]);
      }
      var sMin = Math.min.apply(null, s), sMax = Math.max.apply(null, s);
      var tMin = Math.min.apply(null, t), tMax = Math.max.apply(null, t);
      // Se abre alrededor del CENTRO: crecer solo hacia un lado correria la caja fuera del
      // vano que esta senialando.
      var fs = Math.max(0, CTX.ladoMinimoCaja - (sMax - sMin)) / 2 + CTX.margenCaja;
      var ft = Math.max(0, CTX.ladoMinimoCaja - (tMax - tMin)) / 2 + CTX.margenCaja;
      sMin -= fs; sMax += fs; tMin -= ft; tMax += ft;
      var esquinas = [[sMin, tMin], [sMax, tMin], [sMax, tMax], [sMin, tMax]], anillo = [];
      for (k = 0; k < esquinas.length; k++) {
        anillo.push([lo[0] + esquinas[k][0] * u[0] + esquinas[k][1] * v[0],
                     la[0] + esquinas[k][0] * u[1] + esquinas[k][1] * v[1]]);
      }
      // El anillo CIERRA repitiendo el primer vertice: uno abierto lo descarta MapLibre sin
      // decir nada y no se dibuja ninguna caja.
      anillo.push(anillo[0]);
      porClase[capa].push({type: 'Feature', properties: {fid: fid},
                           geometry: {type: 'Polygon', coordinates: [anillo]}});
    }
    return porClase.map(function (rasgos) {
      return {type: 'FeatureCollection', features: rasgos};
    });
  }

  function pintarCajas(gd, circuito, sel, clasePorFid) {
    // La ventana entra en la firma porque ahora decide el COLOR: el mismo vano marcado
    // cambia de grupo entre ventanas, y sin esto el recuadro se quedaria con el color del
    // grupo anterior mientras la linea ya cambio.
    var firma = circuito + '|' + ventanaActual() + '|' + Object.keys(sel).sort().join(',');
    if (firma === ULTIMA_CAJA) { return; }
    ULTIMA_CAJA = firma;
    // La caja es una capa del layout, no una traza, asi que va por relayout y no por
    // restyle. Se escribe el `source` de las capas que ya existen y no el arreglo `layers`
    // entero: quitar y poner capas reordena en MapLibre lo que hay debajo. Las cinco van
    // en UN relayout, que es lo que cuesta.
    var colecciones = cajasSeleccion(circuito, sel, clasePorFid), cambios = {};
    for (var c = 0; c < colecciones.length; c++) {
      cambios['map.layers[' + c + '].source'] = colecciones[c];
    }
    Plotly.relayout(gd, cambios);
  }

  // --- La marca automatica -----------------------------------------------------------
  // Al mover el deslizador cambia el sujeto: los vanos que registraron eventos en la
  // ventana nueva no son los mismos que en la anterior, y dejar la marca vieja hace que el
  // mapa, la serie y el reparto sigan describiendo vanos que en esta ventana no tienen
  // ninguna celda. Es un REEMPLAZO y no una suma, por lo mismo: acumular ventanas dejaria
  // marcado todo lo que alguna vez tuvo un evento.
  //
  // Y son los QUINCE de mas UITI, no todos los que tengan alguno. Marcar todos era lo que
  // hacia antes, y en un circuito activo son decenas: la leyenda crecia a seis renglones,
  // las flechas se cruzaban y el panel dejaba de senialar nada en particular. Quince es el
  // numero de cupos con color, serie y flechas propias, asi que marcar mas era marcar
  // vanos que el panel no podia contar.
  //
  // Despues de esto la seleccion vuelve a ser del usuario -- casilla o clic en el mapa,
  // sin tope -- hasta el proximo cambio de ventana o de circuito.
  //
  // Contraparte JS de `top_vanos_de_ventana` (src/chec_local_interpreter/ventanas_015.py),
  // que es lo que el cuaderno 06 usa para lo mismo. Se porta y no se aproxima, incluido el
  // desempate por fid ascendente: sin el, el orden lo decidiria el de las celdas y los dos
  // tableros auto-marcarian vanos distintos sobre el mismo circuito en el mismo periodo.
  function topDeLaVentana(circuito, w) {
    var uiti = UITI_VENTANA[w] || {}, vanos = CTX.vanosPorCircuito[circuito] || [];
    var con = [], i;
    for (i = 0; i < vanos.length; i++) {
      if (uiti[vanos[i]] !== undefined) { con.push(vanos[i]); }
    }
    con.sort(function (a, b) {
      if (uiti[a][0] !== uiti[b][0]) { return uiti[b][0] - uiti[a][0]; }
      return a < b ? -1 : (a > b ? 1 : 0);
    });
    return con.slice(0, CTX.topVentana);
  }

  // Deja marcados EXACTAMENTE esos fids y ninguno mas. Escribe sobre las casillas, que son
  // el estado: un registro paralelo es como la lista, el mapa y el reparto empiezan a
  // contar cosas distintas.
  function marcarSolo(fids) {
    var elegidos = {}, i;
    for (i = 0; i < fids.length; i++) { elegidos[fids[i]] = true; }
    var cajas = d.querySelectorAll('#v4-vanos input[type=checkbox]');
    for (i = 0; i < cajas.length; i++) {
      cajas[i].checked = elegidos[cajas[i].value] === true;
    }
  }

  function autoseleccionar() {
    marcarSolo(topDeLaVentana(d.getElementById('v4-circuito').value, ventanaActual()));
  }

  function activarClicMapa(gd) {
    if (CLIC_LISTO || typeof gd.on !== 'function') { return; }
    CLIC_LISTO = true;
    gd.on('plotly_click', function (ev) {
      if (!ev || !ev.points || !ev.points.length) { return; }
      var pt = ev.points[0];
      // Solo el mapa alterna la seleccion. Se filtra por traza y no por "tiene
      // customdata": la nube y la evolucion tambien la usan, con otro significado, y un
      // clic ahi no debe marcar nada.
      // Van las CINCO familias que dibujan vanos. Las de grupo son nuevas aqui y son las
      // que reciben el cursor sobre un vano con eventos sin marcar: sin ellas, marcar
      // tocando un vano de color no funcionaba, que es justo el caso normal.
      var esMapa = pt.curveNumber === CTX.idx.mapaSinEventos ||
                   pt.curveNumber === CTX.idx.mapaResaltadoSinDato ||
                   CTX.idx.mapaGrupos.indexOf(pt.curveNumber) >= 0 ||
                   CTX.idx.mapaResaltado.indexOf(pt.curveNumber) >= 0;
      if (!esMapa) { return; }
      var fid = pt.customdata;
      if (fid === undefined || fid === null) { return; }
      marcarPorFid(fid);
    });
  }

  // --- Vertices para el hover del vano --------------------------------------------
  // El hover de una traza de lineas en Scattermap NO se resuelve contra la linea: se
  // resuelve contra sus VERTICES. plotly.js mide la distancia del cursor a cada punto
  // con radio max(3, marker.mrc) y descarta lo que quede a mas de `hoverdistance`
  // (20 px por defecto), asi que una linea sin vertices cerca del cursor NO tiene
  // etiqueta -- por mas ancha que sea, el ancho de linea no participa del calculo.
  // Los tramos de MVLINSEC.shp traen EXACTAMENTE 2 vertices (60.053 de 60.053 medidos),
  // uno en cada extremo: en un vano largo (p90 = 388 m, maximo 12 km) el centro de la
  // linea quedaba a mas de 20 px de los dos extremos y no mostraba ningun codigo, ni
  // para el hover ni para el click de seleccion (que lee el mismo punto).
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
    var b = boundsDeTrazas(gd, CTX.idx.mapaGrupos);
    if (!b) {
      // Sin un solo vano con eventos no hay nada que encuadrar. Se cae al circuito
      // completo y se DICE: un boton que no produce ningun cambio visible se lee como
      // roto, y aqui el mapa ya estaba encuadrado en el circuito.
      var aviso = d.getElementById('v4-aviso');
      if (aviso) {
        aviso.textContent = 'Ningun vano registro eventos en este periodo: el mapa se '
                          + 'encuadra sobre el circuito completo.';
      }
      encuadrarCircuito(gd, d.getElementById('v4-circuito').value);
      return;
    }
    var tam = tamanoMapa(gd);
    var vista = encuadre(b, tam[0], tam[1]);
    if (!vista) { return; }
    Plotly.relayout(gd, {'map.center': vista.center, 'map.zoom': vista.zoom});
  }

  (function () {
    var boton = d.getElementById('v4-centrar');
    if (!boton) { return; }
    boton.addEventListener('click', function () {
      var gd = d.getElementById(CTX.div);
      if (gd && gd._fullLayout) { encuadrarEventos(gd); }
    });
  })();

  // `forzar` existe por MapLibre, no por capricho: los redibujados de arranque
  // repiten esta llamada con los mismos argumentos justamente porque el primero se
  // pudo perder mientras el subplot de mapa todavia no estaba montado. Sin la
  // puerta abierta, la firma los cortaria y el mapa se quedaria vacio.
  function dibujarMapa(gd, circuito, sel, forzar) {
    var w = parseInt(d.getElementById('v4-ventana').value, 10) || 0;
    var v = CTX.ventanas[w];
    d.getElementById('v4-ventana-txt').textContent = v.etiqueta + ': ' + v.periodo;

    // Las tres cosas de las que depende el dibujo. La seleccion va por sus claves
    // ordenadas: `elegidos()` devuelve un objeto nuevo en cada llamada, asi que
    // compararlo por identidad no serviria de nada.
    var firma = w + '|' + circuito + '|' + Object.keys(sel).sort().join(',');
    if (!forzar && firma === FIRMA_MAPA) { return; }
    FIRMA_MAPA = firma;

    // El reparto del mapa, en cuatro conjuntos DISJUNTOS por vano:
    //
    //   - con eventos en la ventana  -> traza de SU grupo, color del grupo y ancho 7,0
    //   - sin eventos                -> traza de estructura, negra y ancho 1,5
    //   - marcado y con eventos      -> ademas, halo blanco + trazo del grupo al 40%% mas
    //   - marcado y sin eventos      -> ademas, halo blanco + trazo negro al 40%% mas
    //
    // Lo que esto corrige: antes el color del grupo era SOLO para los marcados, y todo lo
    // demas caia en la estructura negra. O sea que desmarcar un vano no le quitaba el
    // resaltado, le borraba el grupo -- el vano tuvo eventos y pasaba a dibujarse igual
    // que uno que no tuvo ninguno. La marca y la clase son dos cosas distintas y ahora
    // viajan por canales distintos: la clase manda el color y el ancho, la marca agrega el
    // halo, el trazo mas grueso y el recuadro. Es el mismo reparto que hace
    // `capas_mapa_historico` en el cuaderno 06.
    //
    // El mapa no usa opacidad para nada: lo que distingue es color, presencia y grosor.
    var nG = CTX.grupos.length, i, k;
    var elat = [], elon = [], etxt = [], ecd = [];           // sin eventos (estructura)
    var glat = [], glon = [], gtxt = [], gcd = [];           // con eventos, por grupo
    var rlat = [], rlon = [], rtxt = [], rcd = [];           // marcados con eventos
    for (i = 0; i < nG; i++) {
      glat.push([]); glon.push([]); gtxt.push([]); gcd.push([]);
      rlat.push([]); rlon.push([]); rtxt.push([]); rcd.push([]);
    }
    var slat = [], slon = [], stxt = [], scd = [];           // marcados sin eventos
    var geo = geoActual().geo;
    var hlat = [], hlon = [];
    // El grupo de cada vano en ESTA ventana, para que el recuadro se pinte del mismo color
    // que su linea sin volver a clasificar.
    var clasePorFid = {};

    var info = (circuito !== CTX.sinSeleccion) ? CTX.geo[circuito] : null;
    if (info) {
      var uiti = UITI_VENTANA[w];
      var denso = geoDenso(circuito, info);
      for (i = 0; i < info.fids.length; i++) {
        var fid = info.fids[i], dato = uiti[fid];
        var val = dato ? dato[0] : 0, ev = dato ? dato[1] : 0;
        // Sin celda en esta ventana no hay grupo: el vano existe pero no tuvo eventos, y
        // eso es distinto de pertenecer al grupo mas bajo.
        var dst = dato ? grupoDe(ev, val, geo) : -1;
        clasePorFid[fid] = dst;
        var etq = '<b>Vano ' + fid + '</b><br>' + v.etiqueta + ': ' + v.periodo +
                  '<br>Grupo: ' + (dato ? CTX.grupos[dst] : 'sin eventos') +
                  '<br>UITI acumulado: ' + val + '<br>Eventos: ' + ev +
                  (sel[fid] ? (dato ? '<br>(elegido)'
                                    : '<br>(elegido, sin eventos en esta ventana)') : '');
        // El vano entra en la traza de SU grupo, o en la de estructura si en esta ventana
        // no tuvo celda. Los dos conjuntos son disjuntos, asi que ningun vano se dibuja
        // dos veces y el orden de las trazas no puede tapar a uno con el otro.
        var dLat = dst >= 0 ? glat[dst] : elat, dLon = dst >= 0 ? glon[dst] : elon;
        var dTxt = dst >= 0 ? gtxt[dst] : etxt, dCd = dst >= 0 ? gcd[dst] : ecd;
        // Un null entre segmentos corta la linea: sin eso Plotly une el final de un vano
        // con el principio del siguiente. El texto se repite por punto porque el hover se
        // resuelve punto a punto.
        // La etiqueta se repite en CADA vertice densificado: el hover engancha en el
        // punto mas cercano, y todos los del vano dicen lo mismo.
        var dLa = denso.lat[i], dLo = denso.lon[i];
        // `push.apply` y no `concat`: `concat` crea un arreglo nuevo en cada vano, y sobre
        // los cientos de tramos de un circuito grande eso es copiar la lista entera una vez
        // por vano. Aqui hay cinco destinos en vez de uno, asi que el coste se notaria.
        empujar(dLat, dLa); empujar(dLon, dLo);
        dLat.push(null); dLon.push(null);
        // El FID viaja tambien en la posicion del separador: customdata tiene que medir lo
        // mismo que lat/lon o Plotly desalinea el resto de la traza.
        for (k = 0; k < dLa.length; k++) { dTxt.push(etq); dCd.push(fid); }
        dTxt.push(''); dCd.push(fid);
  // --- Marca de inicio y fin de vano ------------------------------------------------
  // Un guion HORIZONTAL sobre cada extremo del vano, para TODOS los vanos, tengan o no
  // eventos. No se puede hacer con un simbolo de marcador: `marker.symbol` de Scattermap
  // solo acepta iconos del sprite del estilo del mapa (lista maki), ahi no hay ningun
  // simbolo de linea horizontal, y usando un simbolo distinto de 'circle' se pierden color
  // y tamaño por punto. Asi que el guion se dibuja como un SEGMENTO mas dentro de la MISMA
  // traza que el vano: hereda su color y su ancho, no agrega ninguna traza, y sirve tambien
  // como punto de hover. Va en la traza del grupo y ya no siempre en la negra, que es lo
  // que hace que el guion tenga el color del vano al que pertenece.
        var oLa = info.lat[i], oLo = info.lon[i], ex, ie;
        for (ex = 0; ex < 2; ex++) {
          ie = ex === 0 ? 0 : oLa.length - 1;
          dLat.push(oLa[ie], oLa[ie], null);
          dLon.push(oLo[ie] - MARCA_VANO, oLo[ie] + MARCA_VANO, null);
          dTxt.push(etq); dTxt.push(etq); dTxt.push('');
          dCd.push(fid); dCd.push(fid); dCd.push(fid);
        }
        // Marcado: se le suma el halo blanco y el trazo un 40%% mas ancho -- del color de
        // su grupo si tuvo eventos, negro si no. El marcado sin celda tambien se resalta,
        // y con el mismo grosor: lo que cambia al no tener grupo es el COLOR, no el peso.
        // Sin esto el halo de 25 px le quedaba encima de una linea de 1,5 y el vano
        // marcado desaparecia en una mancha blanca.
        if (sel[fid]) {
          empujar(hlat, dLa); hlat.push(null);
          empujar(hlon, dLo); hlon.push(null);
          var mLat = dst >= 0 ? rlat[dst] : slat, mLon = dst >= 0 ? rlon[dst] : slon;
          var mTxt = dst >= 0 ? rtxt[dst] : stxt, mCd = dst >= 0 ? rcd[dst] : scd;
          empujar(mLat, dLa); mLat.push(null);
          empujar(mLon, dLo); mLon.push(null);
          for (k = 0; k < dLa.length; k++) { mTxt.push(etq); mCd.push(fid); }
          mTxt.push(''); mCd.push(fid);
        }
      }
    }
    var tr = (info && CTX.trafos[circuito]) || {lat: [], lon: []};
    var sw = (info && CTX.switches[circuito]) || {lat: [], lon: []};
    // Las quince trazas del mapa en UNA llamada, por el mismo motivo que la nube: lo que
    // cuesta es cada restyle que cambia algo, no cuantos datos lleva.
    // El halo va SIN hovertext ni customdata: esta debajo de la linea de color, que ya los
    // lleva, y dos etiquetas en el mismo punto solo se estorban.
    Plotly.restyle(gd, {
      lat: glat.concat([elat], rlat, [slat, hlat, tr.lat, sw.lat]),
      lon: glon.concat([elon], rlon, [slon, hlon, tr.lon, sw.lon]),
      hovertext: gtxt.concat([etxt], rtxt, [stxt, [],
                  tr.lat.map(function () { return '<b>Transformador</b>'; }),
                  sw.lat.map(function () { return '<b>Interruptor / switch</b>'; })]),
      customdata: gcd.concat([ecd], rcd, [scd, [], [], []]),
    }, CTX.idx.mapaGrupos.concat(
         [CTX.idx.mapaSinEventos], CTX.idx.mapaResaltado,
         [CTX.idx.mapaResaltadoSinDato, CTX.idx.mapaHalo, CTX.idx.mapaTrafos,
          CTX.idx.mapaSwitches]));

    pintarCajas(gd, circuito, sel, clasePorFid);

    // La leyenda del mapa ya no se reescribe: los grupos son fijos, asi que sus nombres y
    // colores se imprimen una sola vez en el panel.
    // Recentrar SOLO al cambiar de circuito: si el usuario se acerco a una zona y mueve el
    // slider, volver a encuadrar descartaria el zoom que eligio.
    if (info && info.bounds && circuito !== ULTIMO_CENTRADO) {
      ULTIMO_CENTRADO = circuito;
      encuadrarCircuito(gd, circuito);
    }
  }

  function aplicar() {
    var gd = d.getElementById(CTX.div);
    if (!gd || !gd._fullLayout) { return setTimeout(aplicar, 120); }

    var circuito = d.getElementById('v4-circuito').value;
    // `poblarLista` deja todas las casillas sin marcar, asi que la marca automatica va
    // pegada a ella: sin eso, cambiar de circuito abriria el tablero vacio hasta mover el
    // deslizador.
    //
    // Al aterrizar en un circuito se marca el top del PERIODO y no el de la ventana. Es la
    // pregunta con la que se llega -- donde esta concentrado el riesgo de este circuito --
    // y deja a la evolucion de abajo contando la historia de esos mismos quince vanos. El
    // top de la ventana llega despues, en cuanto se toca el deslizador.
    var tituloPerfil = null;
    if (circuito !== ULTIMO_CIRCUITO) {
      ULTIMO_CIRCUITO = circuito;
      poblarLista(circuito);
      marcarSolo(CTX.topPeriodo[circuito] || []);
      // Aqui y no en cada pasada: el perfil no depende ni de la ventana ni de la
      // seleccion, que son las dos cosas que hacen volver a aplicar().
      tituloPerfil = pintarPerfil(gd, circuito);
    }
    var sel = elegidos(), cu = cuposDe(sel);

    var act = geoActual(), logx = act.logx, logy = act.logy, geo = act.geo;
    var cambioEspacio = act.i !== ULTIMO_ESPACIO;
    ULTIMO_ESPACIO = act.i;
    var C = CTX.celdas, i;

    // Este bucle arma SOLO el dibujo de la nube, que lleva todas las ventanas. El
    // reparto por grupo -- violines, barras y porcentajes -- se filtra por ventana y vive
    // en dibujarReparto().
    var bx = [[], [], [], []], by = [[], [], [], []], bt = [[], [], [], []];
    var qx = [[], [], [], []], qy = [[], [], [], []], qt = [[], [], [], []];
    var sx = [], sy = [], st = [], nombres = [], enLeyenda = [];
    for (i = 0; i < CTX.maxResaltados; i++) {
      sx.push([]); sy.push([]); st.push([]);
      // El nombre se conserva -- es lo que sale en la etiqueta del mouse, y ahi el
      // circuito hace falta: los codigos de vano no dicen de que circuito son --, pero
      // el vano NO entra en la leyenda de arriba.
      //
      // Con quince marcados eran quince entradas que empujaban la leyenda a tres
      // renglones, y la figura tenia que reajustar su margen superior en el navegador
      // para no pisarse el titulo. Lo que la leyenda explica es el COLOR, y el color lo
      // fija el grupo de criticidad, no el vano.
      nombres.push(i < cu.cupos.length
                   ? 'Vano ' + cu.cupos[i] + ' (' + circuito + ')' : '');
      enLeyenda.push(false);
    }
    var ox = [], oy = [], ot = [], oc = [];
    var ciSel = (circuito !== CTX.sinSeleccion) ? CTX.circuitos.indexOf(circuito) : -1;
    var hayVanos = cu.lista.length > 0, hayFoco = hayVanos || ciSel >= 0;
    // La opacidad plena queda para las celdas del circuito elegido en la ventana elegida.
    // Sin circuito no hay interseccion que resaltar y todas las celdas viven en el bucket
    // de la nube, asi que ahi el foco lo decide la ventana sola.
    SIN_CIRCUITO = ciSel < 0;
    VENT_NUBE = [[], [], [], []]; VENT_CIRC = [[], [], [], []];
    VENT_CUPO = []; VENT_OTROS = [];
    var sc = [];
    for (i = 0; i < CTX.maxResaltados; i++) { VENT_CUPO.push([]); sc.push([]); }
    for (i = 0; i < C.fid.length; i++) {
      var g = grupoDe(C.n[i], C.u[i], geo);
      var cupo = cu.de[C.fid[i]], marcado = cupo !== undefined || sel[C.fid[i]] === true;
      var etq2 = '<b>Vano ' + C.fid[i] + '</b>' + (marcado ? ' (elegido)' : '') +
                 '<br>Circuito: ' + CTX.circuitos[C.ci[i]] +
                 '<br>' + CTX.ventanas[C.vi[i]].etiqueta + ': ' +
                 CTX.ventanas[C.vi[i]].periodo +
                 '<br>Grupo: ' + CTX.grupos[g] + '<br>Eventos: ' + C.n[i] +
                 '<br>UITI: ' + C.u[i];
      if (cupo !== undefined) {
        sx[cupo].push(C.n[i]); sy[cupo].push(C.u[i]); st[cupo].push(etq2);
        // El punto resaltado se pinta con el color de SU grupo en esta celda; el anillo
        // del cupo, que es fijo, sigue diciendo de que vano es.
        sc[cupo].push(CTX.colores[g]); VENT_CUPO[cupo].push(C.vi[i]);
      } else if (marcado) {
        ox.push(C.n[i]); oy.push(C.u[i]); ot.push(etq2);
        oc.push(CTX.colores[g]); VENT_OTROS.push(C.vi[i]);
      } else if (C.ci[i] === ciSel) {
        qx[g].push(C.n[i]); qy[g].push(C.u[i]); qt[g].push(etq2);
        VENT_CIRC[g].push(C.vi[i]);
      } else {
        bx[g].push(C.n[i]); by[g].push(C.u[i]); bt[g].push(etq2);
        VENT_NUBE[g].push(C.vi[i]);
      }
    }
    // Dos niveles de opacidad, no tres. Se recalculan en cada `aplicar()`, asi que
    // cambiar de circuito o desmarcar un vano devuelve cada punto al nivel que le toca.
    var leyN = [], leyQ = [];
    for (i = 0; i < 4; i++) { leyN.push(true); leyQ.push(false); }
    // Las 17 trazas del plano se escriben en UNA llamada. Cada restyle que cambia algo
    // dispara un redibujado completo de la figura -- medido en unos 350 ms con las 57
    // trazas y las 110 mil celdas -- asi que el coste lo fija el NUMERO de llamadas, no
    // el tamano de los datos. Los atributos que estas trazas no cambian igual viajan con
    // su valor habitual, porque restyle exige un valor por indice.
    Plotly.restyle(gd, {
      x: bx.concat(qx, sx, [ox]),
      y: by.concat(qy, sy, [oy]),
      hovertext: bt.concat(qt, st, [ot]),
      name: CTX.grupos.concat(CTX.grupos, nombres, ['Otros elegidos']),
      showlegend: leyN.concat(leyQ, enLeyenda, [false]),
      'marker.color': CTX.colores.concat(CTX.colores, sc, [oc]),
      'marker.opacity': opacidadesActuales(),
    }, CTX.idx.nube.concat(CTX.idx.circuito, CTX.idx.elegidos, [CTX.idx.otros]));
    // El contorno solo se toca cuando el foco cambia de estado, no en cada clic.
    if (hayFoco !== ULTIMO_FOCO) {
      ULTIMO_FOCO = hayFoco;
      Plotly.restyle(gd, {opacity: hayFoco ? 0.15 : 0.28}, [CTX.idx.contorno]);
    }
    var layoutReparto = refrescarReparto(gd, act, circuito, cu);

    // Evolucion: un cupo por vano, con su color. Las ventanas sin eventos van en cero y
    // no se omiten: es una serie de tiempo, y omitirlas haria parecer que no existieron.
    var eu = [], en = [], etu = [], eten = [], recorrido = [], cpunto = [];
    for (var s = 0; s < CTX.maxResaltados; s++) {
      var fidS = cu.cupos[s];
      var us = [], ns = [], tu = [], tn = [], pts = [], cp = [];
      for (var w2 = 0; w2 < CTX.ventanas.length; w2++) {
        var dat2 = (fidS !== undefined) ? UITI_VENTANA[w2][fidS] : null;
        // El grupo se evalua celda a celda: el mismo vano puede cambiar de grupo entre
        // ventanas, y ese cambio es justamente lo que el color del punto tiene que contar.
        var gw = dat2 ? grupoDe(dat2[1], dat2[0], geo) : -1;
        us.push(fidS === undefined ? null : (dat2 ? dat2[0] : 0));
        ns.push(fidS === undefined ? null : (dat2 ? dat2[1] : 0));
        cp.push(gw >= 0 ? CTX.colores[gw] : CTX.colorSinGrupo);
        var cab = '<b>Vano ' + fidS + '</b><br>Circuito: ' + circuito +
                  '<br>' + CTX.ventanas[w2].periodo +
                  '<br>Grupo: ' + (gw >= 0 ? CTX.grupos[gw] : 'sin eventos');
        tu.push(cab + '<br>UITI acumulado: ' + (dat2 ? dat2[0] : 0));
        tn.push(cab + '<br>Eventos: ' + (dat2 ? dat2[1] : 0));
        // La flecha solo une ventanas con celda: las de cero no son un punto de la nube.
        if (dat2) { pts.push([dat2[1], dat2[0]]); }
      }
      eu.push(us); en.push(ns); etu.push(tu); eten.push(tn);
      recorrido.push(pts); cpunto.push(cp);
    }
    Plotly.restyle(gd, {
      y: eu.concat(en), hovertext: etu.concat(eten),
      name: nombres.concat(nombres), 'marker.color': cpunto.concat(cpunto),
    }, CTX.idx.serieUiti.concat(CTX.idx.serieEventos));
    pintarPuntoActivo(gd);

    // Las flechas son anotaciones de layout, no una traza. En un eje logaritmico Plotly
    // espera las coordenadas YA en log10, asi que se convierten segun el tipo de eje.
    // Solo las llevan los cupos: quedan acotadas en 8 vanos por 10 tramos.
    var refX = 'x' + CTX.ejes.nubeX.slice(5), refY = 'y' + CTX.ejes.nubeY.slice(5);
    var flechas = [];
    for (var s2 = 0; s2 < recorrido.length; s2++) {
      var pr = recorrido[s2];
      for (var q = 0; q + 1 < pr.length; q++) {
        flechas.push({
          x: logx ? Math.log10(pr[q + 1][0]) : pr[q + 1][0],
          y: logy ? Math.log10(pr[q + 1][1]) : pr[q + 1][1],
          ax: logx ? Math.log10(pr[q][0]) : pr[q][0],
          ay: logy ? Math.log10(pr[q][1]) : pr[q][1],
          xref: refX, yref: refY, axref: refX, ayref: refY,
          showarrow: true, arrowhead: 3, arrowsize: 1.1, arrowwidth: 2,
          arrowcolor: CTX.coloresVanos[s2], standoff: 7, startstandoff: 7, text: '',
        });
      }
    }

    // La grilla del contorno tambien es del espacio: 6.400 evaluaciones que no cambian
    // porque se marque un vano.
    if (cambioEspacio) {
      var ex2 = CTX.extension, n = CTX.resolucion;
      var gx = ejeGrilla(ex2[0], ex2[1], n, logx), gy = ejeGrilla(ex2[2], ex2[3], n, logy);
      var z = [];
      for (var j = 0; j < gy.length; j++) {
        var fila = [];
        for (i = 0; i < gx.length; i++) { fila.push(grupoDe(gx[i], gy[j], geo)); }
        z.push(fila);
      }
      Plotly.restyle(gd, {z: [z], x: [gx], y: [gy]}, [CTX.idx.contorno]);
    }

    var tx = logx ? 'log' : 'linear', ty = logy ? 'log' : 'linear';
    function lim(lo, hi, log) {
      return log ? [Math.log10(lo * 0.85), Math.log10(hi * 1.15)] : [0, hi * 1.05];
    }
    // Las flechas dependen de la seleccion, asi que el relayout va siempre; los tipos y
    // rangos de eje se le suman solo cuando el espacio cambio.
    // Los cambios de layout de toda la pasada -- flechas, ejes y lo que el reparto
    // haya devuelto -- viajan en UNA llamada.
    if (tituloPerfil !== null && fig_anotaciones[CTX.titulos.perfil[0]]) {
      // Mutar el objeto basta: `fig_anotaciones` es una copia SUPERFICIAL de
      // `gd.layout.annotations`, asi que el array que se manda abajo lleva estas mismas
      // referencias ya actualizadas.
      fig_anotaciones[CTX.titulos.perfil[0]].text = tituloPerfil;
    }
    var cambios = {annotations: fig_anotaciones.concat(flechas)};
    for (var cl in layoutReparto) {
      if (Object.prototype.hasOwnProperty.call(layoutReparto, cl)) {
        cambios[cl] = layoutReparto[cl];
      }
    }
    if (cambioEspacio) {
      cambios[CTX.ejes.nubeX + '.type'] = tx;
      cambios[CTX.ejes.nubeY + '.type'] = ty;
      cambios[CTX.ejes.nubeX + '.range'] = lim(ex2[0], ex2[1], logx);
      cambios[CTX.ejes.nubeY + '.range'] = lim(ex2[2], ex2[3], logy);
      cambios[CTX.ejes.violinUiti + '.type'] = ty;
      cambios[CTX.ejes.violinEventos + '.type'] = tx;
      // Los rangos de barras y violines los fija dibujarReparto(), que es quien sabe
      // sobre que conjunto de celdas se estan calculando.
    }
    Plotly.relayout(gd, cambios);

    dibujarMapa(gd, circuito, sel);
    // Idempotente: se registra una sola vez, la primera vez que la figura esta lista.
    activarClicMapa(gd);

    var nSel = cu.lista.length, sobran = nSel - cu.cupos.length;
    // Cuantos de los marcados tienen celda en la ventana ACTIVA. Es el mismo renglon que
    // el simulador pone bajo su lista de vanos, y aqui hace la misma falta desde que la
    // marca automatica del circuito es el top del PERIODO: ese top puede concentrarse en
    // un mes y dejar a los quince sin un solo evento en la ventana con la que se abre el
    // tablero -- medido en AGU23L12, cuyo top del periodo vive en V3-V4 y no comparte ni
    // un vano con V1. El mapa los dibuja entonces en negro y con el ancho del resaltado,
    // que es lo correcto -- no tuvieron eventos aqui -- pero sin decirlo se lee como que
    // el tablero se rompio.
    var uitiW = UITI_VENTANA[ventanaActual()] || {}, conCelda = 0;
    for (var q2 = 0; q2 < cu.lista.length; q2++) {
      if (uitiW[cu.lista[q2]] !== undefined) { conCelda++; }
    }
    d.getElementById('v4-aviso').textContent = circuito === CTX.sinSeleccion
      ? 'Seleccione un circuito para listar sus vanos y ver el mapa.'
      : circuito + ': ' + (CTX.vanosPorCircuito[circuito] || []).length +
        ' vanos con eventos en el periodo, ' + nSel + ' marcados, ' + flechas.length +
        ' tramos de flecha.' + (nSel === 0
          ? ' Marque vanos para poblar las barras y los violines: describen solo los'
            + ' marcados en la ventana elegida.'
          : ' De los marcados, ' + conCelda + ' tienen eventos en esta ventana' +
            (conCelda < nSel
              ? '; los otros ' + (nSel - conCelda) + ' van en negro porque aqui no '
                + 'registraron ninguno.'
              : '.')) + (sobran > 0
          ? ' Solo los primeros ' + CTX.maxResaltados + ' llevan color propio, leyenda,' +
            ' flechas y serie de evolucion; los otros ' + sobran + ' se resaltan en gris.'
          : '');
    // Despues del restyle, no antes: el alto de la leyenda solo se puede medir cuando
    // ya se redibujo con las entradas de esta seleccion.
    setTimeout(function () { ajustarMargenSuperior(gd); }, 0);
  }

  // Los titulos de los subplots tambien son anotaciones: hay que conservarlos al
  // reescribir `annotations` con las flechas, o desaparecen en el primer cambio.
  var fig_anotaciones = (function () {
    var gd = d.getElementById(CTX.div);
    return (gd && gd.layout && gd.layout.annotations) ? gd.layout.annotations.slice() : [];
  })();

  ['v4-circuito'].forEach(function (id) {
    var el = d.getElementById(id);
    if (el) { el.addEventListener('change', aplicar); }
  });
  // El slider repinta el mapa y rehace el reparto de la ventana. No cambia la particion:
  // los centroides siguen ajustados sobre las 11 ventanas, solo cambia que celdas se
  // cuentan. El reparto va con retardo porque su restyle es el mas caro de la figura y el
  // evento 'input' se dispara en cada paso del arrastre; el mapa se mantiene inmediato.
  var sl = d.getElementById('v4-ventana');
  if (sl) {
    var pendiente = null, cuadro = null;
    sl.addEventListener('input', function () {
      var gd = d.getElementById(CTX.div);
      if (!gd || !gd._fullLayout) { return; }
      // `input` se dispara en CADA paso del arrastre, y cada paso encargaba un
      // dibujado completo que el hilo principal se comia en serie: 2.889 ms de CPU
      // en un arrastre de seis ventanas, medido. Con un cuadro de por medio se
      // dibuja una sola vez por refresco de pantalla y gana el ultimo estado, que
      // es justo lo que el usuario esta pidiendo mientras arrastra.
      if (cuadro !== null) { return; }
      cuadro = requestAnimationFrame(function () {
        cuadro = null;
        dibujarAlVuelo(gd);
      });
    });

    // Lo que sigue al dedo mientras se arrastra. Lo caro -- la nube, el reparto y
    // las series -- espera al antirrebote de abajo.
    function dibujarAlVuelo(gd) {
      // La marca va ANTES del dibujo: el mapa de esta ventana tiene que salir ya con los
      // vanos que le corresponden, no con los de la ventana anterior.
      autoseleccionar();
      dibujarMapa(gd, d.getElementById('v4-circuito').value, elegidos());
      // El punto grande de la evolucion sigue al deslizador EN VIVO, como el mapa: son
      // once numeros por cupo. Lo caro -- la opacidad de 110 mil celdas y el reparto --
      // sigue con retardo.
      pintarPuntoActivo(gd);
      if (pendiente) { clearTimeout(pendiente); }
      pendiente = setTimeout(function () {
        pendiente = null;
        // Antes aqui bastaba con el reparto y las opacidades: la ventana cambiaba pero la
        // seleccion no. Ahora la ventana TRAE una seleccion distinta, y de ella dependen
        // ademas los cupos de color, la leyenda, las series de evolucion y las flechas.
        // Eso es exactamente lo que rehace `aplicar()`, que ya incluye las dos llamadas
        // que estaban aqui.
        //
        // Y va SIEMPRE, sin el `if (ULTIMA_VENTANA === ventanaActual()) return` que tenia.
        // Esa guarda ahorraba la pasada cuando el arrastre terminaba en la misma ventana en
        // que empezo, y era correcta mientras la seleccion no dependiera del deslizador.
        // Ahora `autoseleccionar()` ya corrio arriba y REEMPLAZO lo que hubiera marcado a
        // mano, asi que volver al mismo indice no deja las cosas como estaban: dejaba la
        // nube, el reparto, las series y el aviso describiendo la seleccion anterior sobre
        // un mapa que ya mostraba la nueva. Medido en el navegador. Lo caro de `aplicar()`
        // lo siguen frenando el antirrebote y la firma de `refrescarReparto`.
        aplicar();
      }, 140);
    }
  }
  d.getElementById('v4-todos').addEventListener('click', function () {
    d.querySelectorAll('#v4-vanos input[type=checkbox]').forEach(function (c) { c.checked = true; });
    aplicar();
  });
  d.getElementById('v4-ninguno').addEventListener('click', function () {
    d.querySelectorAll('#v4-vanos input[type=checkbox]').forEach(function (c) { c.checked = false; });
    aplicar();
  });
  aplicar();
  [700, 2000].forEach(function (ms) {
    setTimeout(function () {
      var gd = d.getElementById(CTX.div);
      if (gd && gd._fullLayout) {
        var circ = d.getElementById('v4-circuito').value;
        dibujarMapa(gd, circ, elegidos(), true);
        encuadrarCircuito(gd, circ);
        ajustarMargenSuperior(gd);
      }
    }, ms);
  });

  // La figura es responsive: al cambiar el tamano de la ventana se redibuja, el mapa pasa a
  // tener otro tamano en pixeles y la leyenda cambia de alto. Las dos medidas se rehacen, o
  // el circuito queda recortado y el titulo se superpone con la leyenda. Con retardo, porque
  // 'resize' se dispara en cada cuadro del arrastre.
  var reencuadre = null;
  window.addEventListener('resize', function () {
    if (reencuadre) { clearTimeout(reencuadre); }
    reencuadre = setTimeout(function () {
      reencuadre = null;
      var gd = d.getElementById(CTX.div);
      var sel = d.getElementById('v4-circuito');
      if (!gd || !gd._fullLayout || !sel) { return; }
      encuadrarCircuito(gd, sel.value);
      ajustarMargenSuperior(gd);
    }, 200);
  });
})();
</script>
''' % json.dumps(dict(CONTEXTO, idx=IDX, ejes=EJES, titulos=TITULOS_N),
                     separators=(',', ':'))

    # include_plotlyjs=True embebe plotly.js en esta misma salida: el panel, la figura y su
    # libreria viajan juntos, de modo que el tablero se ve igual exportado a HTML o en nbviewer.
    # `default_width='100%'` solo surte efecto porque la figura NO lleva `width` (ver la celda
    # anterior), y `responsive` la recalcula al cambiar el tamano de la ventana.
    FIGURA_HTML = pio.to_html(fig, include_plotlyjs=True, full_html=False, div_id=DIV,
                              default_width='100%', config={'responsive': True})

    CSS_DOS_COLUMNAS = '''
<style>
  /* Los controles a la izquierda y las figuras a la derecha, en vez de una barra
     horizontal encima de una figura de 960 a 1.700 px de alto: asi elegir un circuito y
     ver que le hace al mapa dejan de estar en extremos opuestos del scroll. */
  /* `align-items` se deja en su valor por defecto -- `stretch` -- a proposito. Con
     `flex-start` cada columna media lo que media SU contenido, y al lado de una figura
     de 1.700 px el panel de control ocupaba su trozo de arriba: el fondo verde se
     cortaba a un tercio de la pantalla y la union de las dos columnas se leia como un
     recorte. */
  .cuerpo-2col {
    display: flex; gap: 14px;
    width: 100%; box-sizing: border-box;
  }
  /* `min-width: 0` apaga el `min-width: auto` que trae todo hijo de flex. Sin el, el
     ancho minimo del div de plotly manda sobre el 70% declarado y la pagina scrollea a
     lo ancho: el 30/70 se escribe pero no se cumple. */
  /* El ancho de los controles viaja en una variable CSS con 30% por defecto: este mismo
     bloque va COPIADO en cada cuaderno que lo usa y una prueba exige que las copias
     sean identicas, asi que un tablero que quiera otro reparto lo dice en SU marcado --
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
     panel-v -- para que este mismo bloque sirva para cualquiera de ellos. Hoy lo usan el
     01 y el 04; el 02 y el 03 volvieron a apilar panel y figura. */
  /* Que la COLUMNA mida el alto entero no basta: el panel es quien lleva el fondo, y
     sin `height: 100%` sigue midiendo su contenido dentro de una columna alta. Con el
     alto entero, el contenido pegado arriba deja un vacio largo debajo, asi que
     `justify-content: center` lo alinea verticalmente con el panel de figuras. */
  .cuerpo-2col > .col-controles > [class^="panel-"] {
    flex-direction: column; flex-wrap: nowrap; align-items: stretch; max-width: 100%;
    height: 100%; justify-content: center;
  }
  /* Y sus controles dejan de exigir un ancho que la columna ya no tiene. */
  .cuerpo-2col > .col-controles select,
  .cuerpo-2col > .col-controles input,
  .cuerpo-2col > .col-controles button { max-width: 100%; min-width: 0; }
  /* Las filas del panel se parten cuando no caben, en vez de salirse por la derecha. */
  .cuerpo-2col > .col-controles > [class^="panel-"] > div { flex-wrap: wrap; }
  /* Y cada hijo recupera el alto de SU contenido.
     `flex-basis: 100%` se escribio para una FILA, donde significa "ocupa el ancho entero"
     -- asi se fuerza un salto de linea en una barra de controles --. Girado el panel a
     columna, ese 100% se lee contra el ALTO. Mientras el panel media lo que media su
     contenido daba igual; al estirarlo al alto de la columna, cada hijo empezo a reclamar
     su parte: medido, un rotulo de 40 px ocupaba 222 y el panel del 04 abria un hueco de
     430 px en mitad de la columna. */
  /* `!important` porque esos hijos traen `flex-basis:100%` EN LINEA -- un atributo
     `style` gana a la hoja --, y es el mismo motivo por el que mas abajo se vencen sus
     `min-width` en linea. Sin el, el basis inline seguia mandando y con `flex-shrink: 0`
     cada hijo pasaba de 222 px a 1.057: peor que antes. */
  .cuerpo-2col > .col-controles > [class^="panel-"] > * { flex: 0 0 auto !important; }
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
    # El boton de encuadre, ENCIMA del mapa y a su izquierda, con la misma forma que en el
    # 01 y en el 03. Estaba en la ultima fila del panel de control, a media pantalla de lo
    # unico que mueve.
    #
    # La sangria se calcula igual que en el 03 y por el mismo motivo: el mapa es la casilla
    # (1,9) de una rejilla de quince columnas, asi que no empieza en el margen de la figura,
    # y la figura es responsiva. `MAPA_IZQ` se LEE de la figura -- sale del reparto de
    # columnas y del espaciado --, nunca se escribe a mano: un literal no fallaria el dia
    # que alguien toque la rejilla, se desalinearia en silencio.
    MAPA_IZQ = float(fig.layout.map.domain.x[0])
    MAPA_DER = float(fig.layout.map.domain.x[1])
    BARRA_ENCUADRE = f"""
<style>
  /* El boton se alinea con el borde DERECHO del mapa, y esa cuenta no la hace
     `text-align: right`: el mapa no llega al borde de la figura -- entre los dos estan el
     margen derecho del `layout`, en pixeles, y el resto del area de dibujo hasta donde
     acaba su dominio --, asi que alinear contra la ventana desfasa, y el desfase crece
     con el ancho de la pantalla.
     `border-box` y `width: 100%`: sin ellos ese `calc` se SUMA al ancho en vez de caber
     dentro. Es lo que dejo al tablero 04 saliendose 666 px de la pantalla. */
  .barra-encuadre {{ display: flex; justify-content: flex-end;
                     padding: 0 calc({MARGEN_DER}px + (100% - {MARGEN_IZQ + MARGEN_DER}px) * {1 - MAPA_DER:.5f}) 0 0;
                     margin: 0 0 6px 0; box-sizing: border-box; width: 100%; }}
  /* El estilo es el del boton del 01 y el 03, que copian el del simulador: el gris por
     defecto de un `widgets.Button` de Jupyter. Aqui hay que escribirlo porque este
     tablero es HTML estatico y no trae la hoja de estilos de los widgets. */
  .barra-encuadre button {{
    font-family: Arial, sans-serif; font-size: 13px; font-weight: 400;
    color: rgba(0, 0, 0, 0.87); background: rgb(238, 238, 238);
    border: 0; border-radius: 2px; padding: 0 10px;
    width: 260px; height: 28px; line-height: 28px; margin: 2px;
    text-align: center; cursor: pointer;
  }}
  .barra-encuadre button:hover {{ background: rgb(224, 224, 224); }}
</style>
<div class="barra-encuadre">
  <button type="button" id="v4-centrar"
    title="Encuadra el mapa sobre los vanos que registraron eventos en el periodo elegido. El encuadre automatico usa el circuito completo, que en un circuito largo deja los vanos con eventos apretados en una esquina.">Centrar mapa</button>
</div>
"""

    # La barra del boton, arriba de la columna de figuras.
    PANEL_COMPLETO = CSS_DOS_COLUMNAS + (
        '<div class="cuerpo-2col">'
        f'<div class="col-controles">{PANEL_HTML}</div>'
        f'<div class="col-figuras">{BARRA_ENCUADRE}{FIGURA_HTML}</div>'
        '</div>'
    ) + PANEL_JS


    # El MISMO html, envuelto en un documento minimo, escrito a disco y abierto en el navegador:
    # alli el tablero usa todo el ancho de la pantalla en vez del de la celda. No se vuelve a
    # serializar nada -- se reusa PANEL_COMPLETO, que ya trae plotly.js embebido -- de modo que
    # el archivo funciona sin conexion y sin el cuaderno.
    def exportar_y_abrir(html_panel, *, abrir=True):
        import webbrowser

        _por_defecto = REPO_ROOT / 'reports' / 'paneles' / '04_uiti_vano_trayectorias_vano.html'
        destino = Path(ruta_html) if ruta_html is not None else _por_defecto
        destino.parent.mkdir(parents=True, exist_ok=True)
        documento = (
            '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<title>Agrupamiento y evolucion a nivel de vano con ventana deslizante</title>\n'
            # margen 0 y un div al 100%: sin esto el navegador deja el margen por defecto del
            # body y la figura no llega a los bordes de la pantalla.
            '<style>html,body{margin:0;padding:12px;box-sizing:border-box;'
            'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;'
            'color:#2b2b2b;background:#fff;}'
            f'#{DIV}{{width:100%;}}</style>\n</head>\n<body>\n'
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
        """Escribe TABLA en reports/reportescircuitos/artifacts/."""
        if destino is None:
            destino = (REPO_ROOT / 'reports' / 'reportescircuitos' / 'artifacts' /
                       'uiti_vano_ventanas.csv')
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        TABLA.to_csv(destino, index=False)
        return destino


    ruta = guardar_tabla()
    print(f'{len(TABLA):,} filas -> {_corta(ruta, REPO_ROOT)}')
    TABLA.groupby('ventana')['uiti_acumulado'].agg(['count', 'sum']).round(1)

    return RUTA_PANEL
