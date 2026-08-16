"""El tablero del clima: nube por vano y violines, para los 208 circuitos.

## De donde sale este modulo

Es el cuaderno `01_uiti_vano_clima.ipynb`, movido aqui. La aplicacion de escritorio
lo construia leyendo el `.ipynb` y ejecutando sus celdas con `exec()`, de modo que la
fuente real de un tablero era JSON de cuaderno: sin imports, sin pruebas que lo
pudieran llamar, y con el orden de las celdas como unica estructura.

## Como esta partido, y por que asi

Arriba, a nivel de modulo, lo que es CONSTANTE: las seis variables, la paleta del
mapa, los tamanos y la tipografia. Ahi tiene que estar, y no dentro de la funcion,
porque son el contrato que comparten los cuatro tableros -- que un color signifique
lo mismo en los cuatro mapas se comprueba leyendo estos nombres, y encerrados en una
funcion dejan de ser legibles desde fuera.

Abajo, dentro de `construir()`, la tuberia: cargar, agregar, ensamblar, dibujar,
escribir. Sigue siendo un guion largo y eso es deliberado. Cada paso usa casi todo lo
que dejo el anterior -- son decenas de nombres cruzando --, asi que partirlo en
funciones exige inventar fronteras que el cuaderno nunca tuvo. Hacerlo A LA VEZ que
se mueve significaria que un fallo no dice si vino del corte o del traslado.

Este paso es un TRASLADO, y se puede afirmar que es fiel: el HTML que sale es
identico byte a byte al que producia el cuaderno, comprobado contra
`tests/golden/tableros_pre_migracion/`. El codigo se extrajo de las celdas, no se
volvio a teclear. Reorganizarlo es un cambio aparte, y con el golden ya en su sitio
se puede hacer despues sin apostar.

## Lo unico que cambia respecto del cuaderno

- `display(HTML(...))` desaparece: no hay kernel ni celda donde pintar.
- `REPO_ROOT`, el destino del HTML y el abrir-en-navegador dejan de deducirse del
  directorio de trabajo o de una constante, y los pasa quien llama.
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

# Las 4 variables climaticas del modelo, cada una con columnas horarias _0.._24. Los
# violines usan solo las 12 primeras (_0.._11, la "ventana" de 03/04); la nube usa
# las 25 completas de LAS 4 -- no solo de una -- porque el <select> del panel cambia de
# variable en el navegador sin volver a correr Python, y el circuito activo tambien
# cambia en vivo, asi que hace falta traer las 4 variables de LOS 208 circuitos.
VARS = ['prep', 'temp', 'wind_gust_spd', 'wind_spd']
# Dos variables ESTATICAS por vano: entran a los violines Y a la nube del mapa, pero no
# tienen serie horaria -- viajan con UN valor por vano en vez de 25 rezagos, y el slider
# de hora se deshabilita mientras una de ellas este activa.
VARS_ESTATICAS = ['NR_T', 'DDT']
NOMBRES_VARS = {
    'prep': 'Precipitacion', 'temp': 'Temperatura',
    'wind_gust_spd': 'Rafaga de viento', 'wind_spd': 'Velocidad del viento',
    'NR_T': 'Riesgo por vegetacion', 'DDT': 'Descargas a tierra',
}
# Las 6 variables de los violines, en el orden de la grilla 2 filas x 3 columnas.
VARS_VIOLIN = VARS + VARS_ESTATICAS

# Unidad de medida de cada variable, para el ylabel de su violin.
#  - Las 4 climaticas llegan de Open-Meteo con sus unidades por defecto (ver VAR_MAP en
#    `chec_local_interpreter/clima_engine.py`, que no pide `*_unit`): precipitation en
#    mm, temperature_2m en °C, wind_speed_10m y wind_gusts_10m en km/h.
#  - Las 2 estaticas salen del diccionario `data/Variables_seleccion.xlsx`:
#    NR_T = "Nivel de riesgo por vegetacion asociada al vano" (indice adimensional),
#    DDT = "Densidad de descargas a tierra promedio año".
UNIDADES = {
    'prep': 'mm', 'temp': '°C', 'wind_gust_spd': 'km/h', 'wind_spd': 'km/h',
    'NR_T': 'indice', 'DDT': 'descargas/km²/año',
}
VENTANA_HORAS = 12  # _0..11, para el promedio por evento que alimenta los violines
LAG_MAX = 24  # _0..24, el rezago horario completo (25 puntos) que recorre la nube

# --- Parametro del cuaderno ---------------------------------------------------------
# VARIABLE_CLIMA: variable activa de la nube AL ABRIR el panel. Un <select> del propio
# panel deja cambiarla en vivo entre LAS 6 (las 4 climaticas por rezago horario y las 2
# estaticas del vano) sin volver a ejecutar Python; este valor solo decide con cual
# arranca. (Ya no hay parametro CIRCUITO que filtre la base: los 208 circuitos viajan
# todos, y el circuito activo se elige tambien desde el panel, en vivo -- ver la celda
# de ranking mas abajo para el circuito con el que arranca el panel.)
VARIABLE_CLIMA = 'prep'
assert VARIABLE_CLIMA in VARS_VIOLIN, f'VARIABLE_CLIMA debe ser una de {VARS_VIOLIN}'

# ABRIR_EN_NAVEGADOR: ademas de pintar el panel dentro del cuaderno, escribe el MISMO
# HTML autocontenido en reports/paneles/ y lo abre en el navegador por defecto. Ahi el
# panel usa todo el ancho de la pantalla, no el de la celda de Jupyter. Ponerlo en False
# para no abrir nada (por ejemplo al ejecutar en Databricks, Colab o nbconvert, donde no
# hay navegador local que abrir).
assert set(UNIDADES) == set(VARS_VIOLIN), 'cada violin necesita su unidad de medida'


# ARCHIVO_DATOS: la base puede actualizarse (mas dias, otro corte temporal, un v4). Todo
# lo que hay que tocar para apuntar a otra tabla es esta linea -- el nombre ya no esta
# enterrado dentro de find_repo_root().
ARCHIVO_DATOS = 'data/Indicadores_vano_v3.csv'


# Sube desde el cwd hasta encontrar ARCHIVO_DATOS, para que el cuaderno funcione sin
# importar desde que directorio se ejecute (Jupyter local o Colab/Kaggle).
def find_repo_root():
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / ARCHIVO_DATOS).exists():
            return candidate
    raise FileNotFoundError(
        f'No se encontro {ARCHIVO_DATOS} subiendo desde {Path.cwd()}. '
        'Si la base cambio de nombre, actualiza ARCHIVO_DATOS.')




# FID_VANO llega numerico con sufijo '.0' inconsistente entre filas; se normaliza igual
# que `chec_local_interpreter.plotting._norm_map_id`, para que el cruce con la
# geometria no pierda vanos por formato.
def _norm_id(serie):
    return (serie.astype('string').str.strip().str.replace(r'\.0$', '', regex=True)
            .replace({'': pd.NA, '<NA>': pd.NA, 'nan': pd.NA, 'None': pd.NA}))


# Columnas: la base habitual + NR_T/DDT (violines estaticos) + las 25 horas de LAS 4
# variables climaticas (nube; las 12 de los violines quedan enteramente contenidas ahi,
# sin columnas extra). SIN filtrar circuito -- los 208 viajan todos.
COLUMNAS_BASE = ['CIRCUITO', 'FID_VANO', 'UITI_VANO', 'FECHA'] + VARS_ESTATICAS
COLUMNAS_NUBE = [f'{v}_{h}' for v in VARS for h in range(LAG_MAX + 1)]
COLUMNAS = COLUMNAS_BASE + COLUMNAS_NUBE

# Misma paleta y mismos anchos que 03/04: un color de mapa significa lo mismo en
# toda la familia de cuadernos, y el vano sin eventos se ve igual en todos.
CLASES_MAPA = ['Bajo', 'Medio', 'Medio-Alto', 'Alto']
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
COLORES_MAPA = ['rgb(26,150,65)', 'rgb(242,194,0)', 'rgb(239,108,0)', 'rgb(198,40,40)']
COLOR_SIN_EVENTO = 'rgb(0,0,0)'
COLOR_TRAFO = '#f59e0b'
COLOR_SWITCH = '#7c3aed'
# Equipos: los tamaños de antes (6 y 5 px) eran de cuando la figura media 880 px de alto
# y la nube 26 px. Con la figura al doble y circulos de nube de 78 px se volvieron
# invisibles, asi que suben en la misma proporcion.
TAM_TRAFO = 14
TAM_SWITCH = 12
# Capa de UITI por vano: ancho al DOBLE (era 3.5) y OPACA. Los vanos SIN eventos ese dia no
# reciben nada de esta capa -- solo queda su linea negra de estructura, de 1,5 px.
#
# La opacidad era 0.5 y se sube a 1.0 porque a media tinta el color dejaba de ser el de la
# escala. Compuesto contra el fondo claro de carto-positron, `Alto` -- rgb(198,40,40) -- se
# pintaba rgb(220,140,137), un rosa apagado, y `Bajo` quedaba a un paso del
# color del fondo. Peor todavia: sobre el nucleo negro de la estructura la misma clase daba
# otro color (rgb(99,20,20) para `Alto`), asi que un vano se veia de dos tonos distintos segun
# el pixel, y ninguno de los dos coincidia con la muestra de color que el panel imprime en su
# leyenda. Opaca, lo que se ve en el mapa ES el color umbralizado del tablero.
ANCHO_MAPA = 7.0
OPACIDAD_UITI = 1.0
ANCHO_SIN_EVENTOS = 1.5
# Tono base de cada variable, TOMADO DE SU PROPIA ESCALA del mapa (ver ESCALA_POR_VAR,
# mas abajo): un punto fijo bastante saturado de la misma rampa que pinta los circulos.
# Asi el violin de una variable, la serie derecha de (1,3) y su nube del mapa hablan el
# mismo idioma cromatico -- antes eran colores solidos elegidos a mano, que ya no tenian
# relacion con la escala.
# Contrapartida asumida: rafaga y velocidad del viento comparten escala (BuGn), asi que
# sus violines quedan del MISMO tono. Se distinguen por su titulo y por el <select>.
_TONO_T = 0.72  # punto de la rampa: saturado, pero sin llegar al extremo casi negro

NUBE_TAM = 78  # 3x el tamaño anterior (26): los circulos de la variable activa mandan

# La nube ya NO codifica el valor con la opacidad: lo codifica con el COLOR, recorriendo
# una escala secuencial propia de cada variable. La opacidad pasa a ser una constante --
# la misma para todos los puntos -- porque con circulos de 78 px los marcadores de vanos
# vecinos se solapan y necesitan dejar ver la red por debajo.
# En Scattermap `marker.opacity` es un escalar DE TRAZA (no admite un valor por punto),
# que es justo lo que hace falta aqui; y `marker.color` puede llevar los VALORES crudos
# mas `colorscale`/`cmin`/`cmax`, asi que el color lo resuelve Plotly y el JS solo manda
# numeros. Eso reemplaza por completo a los escalones de alpha invertidos previos.
NUBE_OPACIDAD = 0.4

# Escala de color por variable. `cmin`/`cmax` se fijan sobre el DATASET COMPLETO
# (RANGO_GLOBAL, mas abajo), no sobre el circuito activo: un color significa el mismo
# valor en cualquier circuito que se elija en el panel.
# Precipitacion va en VERDES. Se usa `algae` (cmocean) y no `Greens` a proposito: en
# `Greens` el punto _TONO_T=0.72 cae en rgb(42,147,75), que es EXACTAMENTE el tono que
# ya produce NR_T -- los dos violines quedarian indistinguibles, y sumados a los dos de
# viento (BuGn, rgb(42,147,81)) serian 4 de 6 violines del mismo verde. `algae` es una
# rampa verde de punta a punta (rgb(214,249,207) -> rgb(17,36,20), sin pasar por teal)
# cuyo tono rgb(22,97,62) queda a 55 unidades RGB del de NR_T: se lee verde, pero se
# distingue. Para el verde canonico basta cambiar 'algae' por 'Greens'.
ESCALA_POR_VAR = {
    'prep': 'algae',
    'temp': 'OrRd',
    'wind_gust_spd': 'BuGn',
    'wind_spd': 'BuGn',
    'NR_T': 'Greens',
    'DDT': 'Oranges',
}
assert set(ESCALA_POR_VAR) == set(VARS_VIOLIN), 'cada variable de la nube necesita su escala'

from plotly.colors import sample_colorscale as _muestrear

TONO_POR_VAR = {_v: _muestrear(ESCALA_POR_VAR[_v], [_TONO_T], colortype='rgb')[0]
                for _v in VARS_VIOLIN}
# El violin de cada variable toma su tono por posicion (alineado a VARS_VIOLIN).
COLORES_VIOLIN = [TONO_POR_VAR[_v] for _v in VARS_VIOLIN]
assert len(COLORES_VIOLIN) == len(VARS_VIOLIN) == 6
assert all(_c.startswith('rgb(') for _c in COLORES_VIOLIN), (
    'el helper rgba() del panel y el chequeo de tema esperan formato rgb(...)')
# --- Tipografia -----------------------------------------------------------------------
# TODO el texto va al DOBLE de lo que era: la figura se mira en pantalla grande (y ahora
# tambien a pantalla completa en el navegador), donde los 12 px de antes no se leian.
# Una sola fuente de verdad, para que el panel HTML y la figura Plotly no se desalineen:
# el panel replica estos mismos valores en su CSS.
FUENTE_BASE = 18        # ticks, hover, leyenda y fuente por defecto de la figura (era 12)
FUENTE_SUBTITULO = 19   # titulos de cada subplot (eran 12)
FUENTE_EJE_TITULO = 17    # el ylabel con la unidad de medida (era 11)
FUENTE_MARCA_VIOLIN = 14  # las marcas de los violines, que comparten hueco de a cuatro
FUENTE_EJE_VIOLIN = 13    # y su rotulo, que girado ocupa a lo ancho lo que mide de alto
FUENTE_TITULO = 27        # titulo de la figura (era ~17, el default de Plotly)
# El alto de la figura se elige contra el del PANEL de control, que es la otra columna del
# tablero. Medido en el navegador con el panel ya sin sus dos bloques de texto y con dos
# puntos menos de fuente: mide 1.033 px a 1.280 de ventana, 913 a 1.512 y 802 a 1.900 --
# cambia porque su texto se reparte en mas o menos renglones --, asi que ningun numero
# iguala a los tres.
#
# Se cuadra con el de 1.512, que es donde se usa. Y no contra la figura sola sino contra
# la COLUMNA de figuras, que ademas de la figura lleva la barra del boton de encuadre: son
# 44 px medidos, contando los 12 que la barra deja por debajo para no pisar el titulo.
# Con el panel en 967 / 847 / 764 px segun el ancho -- crecio 26 al partirse en dos
# renglones la frase del pie, que ahora dice tambien entre que fechas --, 803 de figura
# mas esos 44 dan 847 y la diferencia a 1.512 queda en 0; en los otros dos anchos, 120 y
# 83, uno hacia cada lado. Con la figura en 2.100 le sobraban 660 px de banda muerta.
ALTO_FIGURA = 803
# El margen izquierdo de la figura es donde EMPIEZA el mapa dentro de su recuadro, y por
# eso lo necesita tambien el boton de encuadre, que va justo encima y alineado con el.
# Con el numero escrito dos veces, mover uno dejaba el boton flotando fuera del mapa.
MARGEN_IZQ_FIGURA = 120
# Y a que distancia del borde de arriba empieza el titulo. Va en PIXELES y se convierte
# a fraccion mas abajo: `title.y` es una fraccion del contenedor, asi que el mismo 0,98
# valia 42 px de aire en una figura de 2.100 y solo 15 en una de 777 -- medido: el
# titulo se salia 11 px por encima del recuadro y aparecia cortado.
TITULO_DESDE_ARRIBA_PX = 34

# Marcadores de las dos series de tiempo de la casilla (2,3). El punto del DIA VIGENTE
# se pinta al TRIPLE, en ambas series, para saber de un vistazo donde esta el slider.
SERIE_TAM = 9
SERIE_TAM_ACTIVO = SERIE_TAM * 3
COLOR_SERIE_UITI = COLORES_MAPA[-1]  # el rojo de `Alto`, el extremo de la escala del mapa



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
    """Construye el tablero y devuelve la ruta del HTML autocontenido.

    `raiz` es la raiz del repositorio; si no se pasa, se busca subiendo desde el
    directorio de trabajo, como hacia el cuaderno.
    """
    REPO_ROOT = Path(raiz) if raiz is not None else find_repo_root()
    ABRIR_EN_NAVEGADOR = bool(abrir)

    # Si la base se actualiza y le falta alguna columna, `usecols` levanta un ValueError que
    # no dice CUAL falta. Se comprueba antes contra la cabecera (leer 0 filas es barato) y se
    # reporta la lista exacta, separando las de negocio de las 25 horas de cada familia.
    _cabecera = set(pd.read_csv(REPO_ROOT / ARCHIVO_DATOS, nrows=0).columns)
    _faltan = [c for c in COLUMNAS if c not in _cabecera]
    if _faltan:
        _fam = sorted({c.rsplit('_', 1)[0] for c in _faltan if c not in COLUMNAS_BASE})
        raise KeyError(
            f'{ARCHIVO_DATOS} no trae {len(_faltan)} columnas que el cuaderno necesita. '
            f'De negocio: {[c for c in _faltan if c in COLUMNAS_BASE] or "ninguna"}. '
            f'Familias horarias incompletas: {_fam or "ninguna"}. '
            'Ajusta VARS / VARS_ESTATICAS o revisa la base.')

    # Se lee con el lector incremental de pyarrow y no con `pd.read_csv`, igual que en 03/04.
    # El resultado es el mismo valor por valor, pero `pd.read_csv(engine='pyarrow')` materializa
    # el archivo de 566 MB antes de descartar las columnas que no se usan: medido sobre estas
    # 106 columnas, 1172 MB de pico contra 437 MB por bloques. Cuesta 0,7 s mas, y ese es el
    # intercambio -- aqui pesa mas el techo de memoria, que es lo que decide si el cuaderno
    # corre en un job de Databricks serverless.
    # Devuelve las columnas en el orden pedido, pero el reindexado explicito se conserva para
    # que el orden no dependa del lector.
    df = pacsv.open_csv(
        str(REPO_ROOT / ARCHIVO_DATOS),
        convert_options=pacsv.ConvertOptions(include_columns=COLUMNAS),
    ).read_all().to_pandas()[COLUMNAS]
    df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
    df['UITI_VANO'] = pd.to_numeric(df['UITI_VANO'], errors='coerce').fillna(0.0)
    df['FID_VANO'] = _norm_id(df['FID_VANO'])
    df['CIRCUITO'] = df['CIRCUITO'].astype(str)
    df = df.dropna(subset=['FID_VANO', 'FECHA'])
    if df.empty:
        raise ValueError(
            f'{ARCHIVO_DATOS} quedo sin filas utiles tras exigir FID_VANO y FECHA validos.')
    df['_dia'] = df['FECHA'].dt.normalize()

    # Promedio de 12h por variable y por vano-evento: la unidad que alimenta los violines.
    for _v in VARS:
        df[f'{_v}_m'] = df[[f'{_v}_{h}' for h in range(VENTANA_HORAS)]].mean(axis=1)

    # Las estaticas ya traen UN valor por fila; se copian a `*_m` para que el resto del
    # cuaderno trate las 6 variables de los violines exactamente igual (misma agregacion,
    # mismo ensamblado, mismo restyle en JS).
    for _v in VARS_ESTATICAS:
        df[f'{_v}_m'] = pd.to_numeric(df[_v], errors='coerce').fillna(0.0)

    print(f'{len(df):,} eventos cargados | {df["CIRCUITO"].nunique()} circuitos | '
          f'variable climatica activa al abrir: {NOMBRES_VARS[VARIABLE_CLIMA]} ({VARIABLE_CLIMA}) | '
          f'violines: {len(VARS_VIOLIN)} variables ({", ".join(VARS_VIOLIN)})')

    # El panel lista TODOS los circuitos y cambia entre ellos EN VIVO -- ya no hace falta
    # elegir uno a mano ni volver a correr el cuaderno. Esta celda solo decide con cual
    # ARRANCA el panel (el de mas dias con eventos) e imprime el ranking completo a modo
    # informativo.
    _ranking = df.groupby('CIRCUITO')['_dia'].nunique().sort_values(ascending=False)
    CIRCUITO = _ranking.index[0]
    print(f'Circuitos disponibles: {len(_ranking)} | circuito inicial del panel: {CIRCUITO} '
          f'({int(_ranking.iloc[0])} dias con eventos) | ranking (top 10):')
    for _c, _n in _ranking.head(10).items():
        _marca = '  <-- circuito inicial' if _c == CIRCUITO else ''
        print(f'  {_c:<12s} {_n:>3d} dias{_marca}')

    # Agregacion vectorizada sobre TODOS los circuitos A LA VEZ (un solo groupby, no un loop
    # por circuito x dia): un vano con varios eventos el mismo dia colapsa a UN valor via
    # PROMEDIO (UITI para el mapa, hora por hora para la nube); un vano con un solo evento
    # ese dia usa ese valor tal cual.
    _gk = ['CIRCUITO', '_dia', 'FID_VANO']
    _uiti_agg = df.groupby(_gk, observed=True)['UITI_VANO'].agg(['sum', 'count'])

    # La nube cubre LAS 6 variables. Las 4 climaticas aportan sus 25 rezagos; las 2 estaticas
    # aportan UNA sola columna (`*_m`) -- repetir 25 veces el mismo numero por vano-dia
    # inflaria el JSON del panel ~50% para no decir nada nuevo, asi que viajan con largo 1 y
    # el JS indexa con clamp.
    COLS_NUBE_POR_VAR = {
        _v: ([f'{_v}_{h}' for h in range(LAG_MAX + 1)] if _v in VARS else [f'{_v}_m'])
        for _v in VARS_VIOLIN
    }
    _cols_nube = [_c for _v in VARS_VIOLIN for _c in COLS_NUBE_POR_VAR[_v]]
    _nube_agg = df.groupby(_gk, observed=True)[_cols_nube].mean()

    # Rango de cada variable sobre TODO el dataset (todos los circuitos a la vez), no por
    # circuito: es el `cmin`/`cmax` de la escala de color de la nube, y un color tiene que
    # significar el mismo valor en cualquier circuito que se elija en el panel. Por eso el
    # cfg de la nube no vive dentro de cada circuito sino una sola vez en la raiz.
    RANGO_GLOBAL = {}
    for _v in VARS_VIOLIN:
        _sub = _nube_agg[COLS_NUBE_POR_VAR[_v]]
        _vmin, _vmax = float(_sub.to_numpy().min()), float(_sub.to_numpy().max())
        if _vmax <= _vmin:
            _vmax = _vmin + 1.0  # variable constante en todo el dataset: evita dividir por cero
        RANGO_GLOBAL[_v] = (round(_vmin, 4), round(_vmax, 4))
    assert set(RANGO_GLOBAL) == set(VARS_VIOLIN)


    # Decimales con los que viaja cada variable al navegador. NO es una constante: sale del
    # rango observado de la propia variable, asi que sigue siendo correcto si la base cambia
    # de unidades o de escala (precipitacion en metros en vez de mm, otro corte temporal...).
    # El criterio es conservar 1/2000 del rango, ~8 veces mas fino de lo que puede distinguir
    # la escala de color (256 niveles) y mucho mas de lo que muestra el hover. Guardar 4
    # decimales para todas era gastar bytes en digitos que nadie puede leer.
    def _decimales_para(vmin, vmax):
        rango = float(vmax) - float(vmin)
        if not np.isfinite(rango) or rango <= 0:
            return 4
        return int(min(8, max(0, np.ceil(-np.log10(rango / 2000.0)))))


    DECIMALES = {_v: _decimales_para(*RANGO_GLOBAL[_v]) for _v in VARS_VIOLIN}
    assert set(DECIMALES) == set(VARS_VIOLIN)

    # Redondeo de las columnas que alimentan los violines ANTES del groupby: asi el `.agg` de
    # abajo solo convierte a lista, sin llamar a round() una vez por grupo y por columna.
    for _v in VARS_VIOLIN:
        df[f'{_v}_m'] = df[f'{_v}_m'].round(DECIMALES[_v])

    # Los violines conservan UNA observacion por vano-evento (no por vano): las 6 columnas
    # `*_m` -- las 4 medias climaticas de 12h y los 2 valores estaticos del vano.
    _cols_m = [f'{_v}_m' for _v in VARS_VIOLIN]
    _viol_grp = df.groupby(['CIRCUITO', '_dia'], observed=True)[_cols_m].agg(list)

    print('rango global por variable (fija cmin/cmax de la escala de color de la nube):')
    for _v in VARS_VIOLIN:
        _lo, _hi = RANGO_GLOBAL[_v]
        print(f'  {NOMBRES_VARS[_v]:<24s} {_lo:>10,.2f} a {_hi:>10,.2f} {UNIDADES[_v]}'
              f'   -> {DECIMALES[_v]} decimales')
    print(f'UITI: {len(_uiti_agg):,} celdas (circuito, dia, vano) | '
          f'nube: {len(_nube_agg):,} celdas x ({len(VARS)} variables x {LAG_MAX + 1} horas '
          f'+ {len(VARS_ESTATICAS)} estaticas x 1) | '
          f'violines: {len(_viol_grp):,} celdas (circuito, dia) x {len(VARS_VIOLIN)} variables')

    import geopandas as gpd

    # Misma geometria y mismo join que usan 03/04 y el mapa del reporte
    # (`chec_local_interpreter.plotting.plot_circuit_map_folium`): las lineas de
    # MVLINSEC.shp se cruzan por FID_VANO normalizado igual que `_norm_map_id`. SIN
    # filtrar circuito -- se arma la geometria de los 208 a la vez, agrupando despues.
    _lineas = gpd.read_file(REPO_ROOT / 'data' / 'GEO' / 'MVLINSEC.shp',
                            columns=['G3E_FID', 'CIRCUITO'])
    if str(_lineas.crs) != 'EPSG:4326':
        _lineas = _lineas.to_crs('EPSG:4326')
    _lineas['FID_VANO_GEO'] = _norm_id(_lineas['G3E_FID'])
    _lineas['CIRCUITO'] = _lineas['CIRCUITO'].astype(str)


    def _puntos_equipo_todos(nombre_shp):
        ruta = REPO_ROOT / 'data' / 'GEO' / nombre_shp
        if not ruta.exists():
            return {}
        _g = gpd.read_file(ruta, columns=['CIRCUITO'])
        if str(_g.crs) != 'EPSG:4326':
            _g = _g.to_crs('EPSG:4326')
        _g['CIRCUITO'] = _g['CIRCUITO'].astype(str)
        _g = _g[_g.geometry.notna() & ~_g.geometry.is_empty]
        _out = {}
        for _circ, _sub in _g.groupby('CIRCUITO'):
            _out[_circ] = {'lat': [round(float(p.y), 5) for p in _sub.geometry],
                           'lon': [round(float(p.x), 5) for p in _sub.geometry]}
        return _out


    TRAFOS_POR_CIRCUITO = _puntos_equipo_todos('GDBCHEC_TRANSFOR.shp')
    SWITCHES_POR_CIRCUITO = _puntos_equipo_todos('SWITCHES.shp')

    # Geometria por circuito: cada vano es un segmento (o varios, si el shapefile lo parte
    # en multiples tramos); el centroide POR VANO -- promedio de TODOS sus puntos, en todos
    # sus tramos -- es lo que usa la nube para ubicar su marcador.
    GEO_POR_CIRCUITO = {}
    for _circ, _sub in _lineas.groupby('CIRCUITO'):
        _geo = {'fids': [], 'lat': [], 'lon': []}
        _acumulado_centro = {}
        for _fid, _geom in zip(_sub['FID_VANO_GEO'], _sub.geometry):
            if _geom is None or _geom.is_empty or pd.isna(_fid):
                continue
            _partes = [_geom] if _geom.geom_type == 'LineString' else list(getattr(_geom, 'geoms', []))
            for _parte in _partes:
                _xs, _ys = _parte.xy
                _lat = [round(v, 5) for v in _ys]
                _lon = [round(v, 5) for v in _xs]
                _geo['fids'].append(str(_fid))
                _geo['lat'].append(_lat)
                _geo['lon'].append(_lon)
                _acc = _acumulado_centro.setdefault(str(_fid), [0.0, 0.0, 0])
                _acc[0] += sum(_lat)
                _acc[1] += sum(_lon)
                _acc[2] += len(_lat)
        if not _geo['fids']:
            continue
        _geo['centros'] = {_fid: [round(_sla / _n, 5), round(_slo / _n, 5)]
                           for _fid, (_sla, _slo, _n) in _acumulado_centro.items()}
        _la = [v for l in _geo['lat'] for v in l]
        _lo = [v for l in _geo['lon'] for v in l]
        _geo['bounds'] = [round(min(_la), 5), round(max(_la), 5), round(min(_lo), 5), round(max(_lo), 5)]
        GEO_POR_CIRCUITO[_circ] = _geo

    print(f'geometria armada para {len(GEO_POR_CIRCUITO)} circuitos | '
          f'{sum(len(TRAFOS_POR_CIRCUITO.get(c, {}).get("lat", [])) for c in GEO_POR_CIRCUITO):,} transformadores | '
          f'{sum(len(SWITCHES_POR_CIRCUITO.get(c, {}).get("lat", [])) for c in GEO_POR_CIRCUITO):,} switches')

    def _fmt_uiti(x):
        return f'{x:,.2f}' if abs(x) < 100 else f'{x:,.0f}'


    # --- Preparacion vectorizada, fuera del loop -----------------------------------------
    # Antes este ensamblado costaba ~5.2 s, casi todo en dos cosas: `.loc[circ].loc[dia]`
    # encadenado sobre un MultiIndex (una busqueda por circuito x dia x variable) y ~595k
    # llamadas a round() de Python, una por valor. Las dos se resuelven aqui arriba de una
    # sola vez: el redondeo pasa a numpy sobre el bloque entero, y la posicion de cada celda
    # (circuito, dia) se resuelve con `groupby.indices`, que devuelve indices enteros.
    assert _uiti_agg.index.equals(_nube_agg.index), (
        'UITI y nube tienen que compartir el indice (circuito, dia, vano); si no, la lista '
        'de vanos de un dia no puede ser comun a los dos')

    _plano = _nube_agg.reset_index()
    _pos_por_celda = _plano.groupby(['CIRCUITO', '_dia'], observed=True, sort=True).indices
    _fids_np = _plano['FID_VANO'].astype(str).to_numpy()
    _uiti_np = _uiti_agg['sum'].to_numpy().round(3)
    _cnt_np = _uiti_agg['count'].to_numpy()
    # Un bloque numpy por variable, ya redondeado con SUS decimales (ver DECIMALES).
    _bloque_var = {_v: _plano[COLS_NUBE_POR_VAR[_v]].to_numpy().round(DECIMALES[_v])
                   for _v in VARS_VIOLIN}

    # --- Paleta de series climaticas -----------------------------------------------------
    # La serie horaria de un vano-dia se REPITE muchisimo: Open-Meteo resuelve el clima en una
    # grilla de varios km, asi que los vanos vecinos de un circuito comparten exactamente la
    # misma serie. Medido sobre las 99.165 celdas vano-dia: prep tiene 7.293 series distintas
    # (13,6x de repeticion), rafaga y velocidad 7.549 (13,1x), temp 40.183 (2,5x), y las dos
    # estaticas 70 y 526 (1.417x y 189x). Serializar cada copia costaba 50,1 MB de los 62,5 MB
    # del JSON.
    # Ahora cada variable viaja como PALETA de series unicas (una sola vez, en la raiz de CTX)
    # mas un indice entero por vano-dia. Es LOSSLESS -- los valores son identicos, solo deja
    # de repetirse la escritura -- y el JS resuelve `paleta[indice]` en un acceso O(1).
    # La paleta es GLOBAL, no por circuito: dos circuitos vecinos comparten clima, y una
    # paleta por circuito perderia esa repeticion.
    _paleta_idx = {_v: {} for _v in VARS_VIOLIN}   # tupla de la serie -> posicion
    NUBE_PALETA = {_v: [] for _v in VARS_VIOLIN}   # posicion -> serie


    def _idx_serie(_v, _fila):
        """Posicion de `_fila` en la paleta de `_v`, agregandola si es nueva."""
        _clave = tuple(_fila)
        _i = _paleta_idx[_v].get(_clave)
        if _i is None:
            _i = len(NUBE_PALETA[_v])
            _paleta_idx[_v][_clave] = _i
            NUBE_PALETA[_v].append(_fila)
        return _i

    _dias_por_circ = {}
    for _c, _d in _pos_por_celda:
        _dias_por_circ.setdefault(_c, []).append(_d)

    # Ensambla el diccionario POR_CIRCUITO: SOLO los circuitos con eventos Y geometria.
    # Los cortes de UITI se calculan UNICOS POR CIRCUITO (sobre todas sus celdas vano-dia, no
    # dia a dia), mismo criterio que 03/04: mover un slider no recolorea el mapa por si
    # solo, y dos dias del mismo circuito se pueden comparar entre si.
    POR_CIRCUITO = {}
    for _circ in sorted(_dias_por_circ):
        if _circ not in GEO_POR_CIRCUITO:
            continue
        _dias = sorted(_dias_por_circ[_circ])
        _dias_ctx = [{'etiqueta': f'D{i + 1}', 'periodo': str(pd.Timestamp(d).date())}
                     for i, d in enumerate(_dias)]

        # `fidsPorDia` es la lista de vanos de cada dia, serializada UNA sola vez. Antes cada
        # vano aparecia como llave repetida en uitiPorDia y en las 6 variables de la nube:
        # 5.7 MB del JSON eran esas llaves duplicadas. Ahora uitiPorDia y nubePorDia son
        # arrays ALINEADOS a esta lista, y el JS reconstruye el diccionario que necesita.
        _fids_por_dia = []
        _uiti_por_dia = []
        _nube_por_dia = {_v: [] for _v in VARS_VIOLIN}
        _violin_por_dia = []
        _uiti_total_por_dia = []
        _mediana_por_dia = {_v: [] for _v in VARS_VIOLIN}
        _vals_uiti = []

        _vc = _viol_grp.loc[_circ]
        for _dia in _dias:
            _pos = _pos_por_celda[(_circ, _dia)]
            _fids_por_dia.append(_fids_np[_pos].tolist())

            _u = _uiti_np[_pos]
            _uiti_por_dia.append([[float(_s), int(_n)] for _s, _n in zip(_u, _cnt_np[_pos])])
            _uiti_total_por_dia.append(round(float(_u.sum()), 3))
            _vals_uiti.extend(float(x) for x in _u if x > 0)

            for _v in VARS_VIOLIN:
                _nube_por_dia[_v].append([_idx_serie(_v, _f)
                                          for _f in _bloque_var[_v][_pos].tolist()])

            # Una lista por variable de violin (6), en el orden de VARS_VIOLIN: es el mismo
            # orden de las trazas y de la grilla. Ya vienen redondeadas desde la celda previa.
            _vr = _vc.loc[_dia]
            _series_dia = [list(_vr[f'{_v3}_m']) for _v3 in VARS_VIOLIN]
            _violin_por_dia.append(_series_dia)
            for _iv, _v3 in enumerate(VARS_VIOLIN):
                _serie_dia = _series_dia[_iv]
                _mediana_por_dia[_v3].append(
                    round(float(np.median(_serie_dia)), DECIMALES[_v3]) if _serie_dia else None)

        if not _vals_uiti:
            _vals_uiti = [0.0]
        _umbrales = [float(round(x, 4)) for x in np.quantile(_vals_uiti, [0.25, 0.5, 0.75])]
        _rotulos = (
            [f'hasta {_fmt_uiti(_umbrales[0])}'] +
            [f'{_fmt_uiti(a)} a {_fmt_uiti(b)}' for a, b in zip(_umbrales, _umbrales[1:])] +
            [f'mas de {_fmt_uiti(_umbrales[-1])}']
        )

        POR_CIRCUITO[_circ] = {
            'dias': _dias_ctx, 'fidsPorDia': _fids_por_dia,
            'uitiPorDia': _uiti_por_dia, 'nubePorDia': _nube_por_dia,
            'violinPorDia': _violin_por_dia, 'umbrales': _umbrales, 'rotulos': _rotulos,
            'uitiTotalPorDia': _uiti_total_por_dia, 'medianaPorDia': _mediana_por_dia,
            'geo': GEO_POR_CIRCUITO[_circ],
            'trafos': TRAFOS_POR_CIRCUITO.get(_circ, {'lat': [], 'lon': []}),
            'switches': SWITCHES_POR_CIRCUITO.get(_circ, {'lat': [], 'lon': []}),
        }

    # Config de la nube: UNA sola, no una por circuito. `vmin`/`vmax` salen de RANGO_GLOBAL
    # (el dataset completo), asi que un color significa el mismo valor aunque se cambie de
    # circuito; el JS los manda a Plotly como `cmin`/`cmax`. `escala` es la escala secuencial
    # de esa variable, `estatica` le dice al JS que la serie tiene largo 1 y que el slider de
    # hora no aplica, y `hue` es el TONO de esa misma escala (TONO_POR_VAR): pinta el violin
    # de la variable y su serie en (1,3), para que los tres elementos usen la misma familia.
    # `muestras` son 5 pares (valor, color) tomados de la propia escala: la tira de leyenda
    # del panel es HTML, no un colorbar de Plotly, asi que necesita los colores ya resueltos.
    #
    # `get_colorscale` resuelve el NOMBRE a la lista explicita de pares [t, 'rgb(...)']. Es
    # obligatorio mandar la lista, NO el nombre: los nombres de escala de plotly.py y los de
    # plotly.js NO son el mismo conjunto. plotly.js solo trae un subconjunto (Blues, Greens,
    # Reds, Viridis, YlGnBu...), asi que 'OrRd', 'BuGn' y 'Oranges' -- que son de ColorBrewer
    # -- no existen ahi y caen EN SILENCIO a la escala por defecto (RdBu, rgb(5,10,172) en el
    # extremo bajo). Medido con una sonda sobre `gd._fullData`: pasando el nombre, 4 de las 6
    # variables pintaban RdBu sin ningun error.
    from plotly.colors import get_colorscale, sample_colorscale

    _PASOS_LEYENDA = 5
    NUBE_CFG = {}
    for _v in VARS_VIOLIN:
        _vmin, _vmax = RANGO_GLOBAL[_v]
        _ts = [_i / (_PASOS_LEYENDA - 1) for _i in range(_PASOS_LEYENDA)]
        _colores = sample_colorscale(ESCALA_POR_VAR[_v], _ts, colortype='rgb')
        NUBE_CFG[_v] = {
            'nombre': NOMBRES_VARS[_v], 'unidad': UNIDADES[_v],
            'vmin': _vmin, 'vmax': _vmax,
            'escala': [[float(_t), _c] for _t, _c in get_colorscale(ESCALA_POR_VAR[_v])],
            'opacidad': NUBE_OPACIDAD,
            'hue': TONO_POR_VAR[_v],
            'estatica': _v in VARS_ESTATICAS,
            'muestras': [[round(_vmin + (_vmax - _vmin) * _t, 4), _c]
                         for _t, _c in zip(_ts, _colores)],
        }
    assert set(NUBE_CFG) == set(VARS_VIOLIN)
    assert all(len(_c['muestras']) == _PASOS_LEYENDA for _c in NUBE_CFG.values())
    # La escala viaja como LISTA de pares, nunca como nombre (ver el comentario de arriba).
    assert all(isinstance(_c['escala'], list) and len(_c['escala']) >= 2
               and _c['escala'][0][0] == 0.0 and _c['escala'][-1][0] == 1.0
               for _c in NUBE_CFG.values()), 'la escala tiene que viajar resuelta, no por nombre'

    CIRCUITOS = sorted(POR_CIRCUITO.keys())
    assert CIRCUITO in POR_CIRCUITO, f'circuito inicial {CIRCUITO!r} sin datos ensamblados'
    # Todo lo que va por dia tiene que estar alineado punto a punto con `fidsPorDia`.
    for _cc in POR_CIRCUITO.values():
        _n = [len(_f) for _f in _cc['fidsPorDia']]
        assert len(_cc['dias']) == len(_n), 'un bloque de vanos por dia'
        assert [len(_x) for _x in _cc['uitiPorDia']] == _n, 'uitiPorDia alineado a fidsPorDia'
        assert all([len(_x) for _x in _cc['nubePorDia'][_v]] == _n for _v in VARS_VIOLIN), (
            'nubePorDia alineado a fidsPorDia')
        assert all(len(_d) == len(VARS_VIOLIN) for _d in _cc['violinPorDia'])
        assert len(_cc['uitiTotalPorDia']) == len(_cc['dias'])
        assert all(len(_cc['medianaPorDia'][_v]) == len(_cc['dias']) for _v in VARS_VIOLIN)
        assert 'nubeCfgPorVar' not in _cc, 'el cfg de la nube vive una sola vez en NUBE_CFG'

    _celdas_totales = sum(len(cc['dias']) for cc in POR_CIRCUITO.values())
    # El largo de la serie ahora se comprueba sobre la paleta (las series reales); sobre
    # nubePorDia solo tiene sentido comprobar que sus indices caen dentro de ella.
    _largos = {_v: {len(_s) for _s in NUBE_PALETA[_v]} for _v in VARS_VIOLIN}
    for _v in VARS_VIOLIN:
        _tope = len(NUBE_PALETA[_v])
        assert all(0 <= _i < _tope for _cc in POR_CIRCUITO.values()
                   for _d in _cc['nubePorDia'][_v] for _i in _d), (
            f'algun indice de nubePorDia[{_v}] cae fuera de su paleta')
    assert all(_largos[_v] <= {LAG_MAX + 1} for _v in VARS), f'las climaticas van con 25 rezagos: {_largos}'
    assert all(_largos[_v] <= {1} for _v in VARS_ESTATICAS), f'las estaticas van con largo 1: {_largos}'
    _series_tot = sum(len(_d) for _cc in POR_CIRCUITO.values() for _d in _cc['nubePorDia'][VARS_VIOLIN[0]])
    print(f'{len(CIRCUITOS)} circuitos ensamblados (con eventos y geometria) | '
          f'{_celdas_totales:,} celdas (circuito, dia) en total')
    print('paleta de series climaticas (deduplicacion lossless):')
    for _v in VARS_VIOLIN:
        _u = len(NUBE_PALETA[_v])
        print(f'  {NOMBRES_VARS[_v]:<24s} {_u:>7,d} series unicas de {_series_tot:,} '
              f'({_series_tot / max(1, _u):>6.1f}x de repeticion)')

    # 14 trazas fijas: 6 violines del dia (uno por variable) + 1 estructura del circuito +
    # 4 clases de cuartil de UITI + 2 de equipos + 1 nube climatica. El panel no crea ni
    # destruye trazas, solo les reescribe los datos -- tanto para mover un slider como para
    # CAMBIAR DE CIRCUITO EN VIVO desde el <select> del panel.
    #
    # Grilla 2 FILAS x 3 COLUMNAS:
    #   (1,1) (1,2)  -> el mapa, sobre dos columnas
    #   (1,3)        -> serie de tiempo con DOBLE eje y (UITI diario / mediana)
    #   fila 2       -> los 6 violines, de a DOS por panel, tambien con doble eje y
    # Las celdas cubiertas por el colspan van como None en `specs`.
    VIOL_COLS = 3
    FILA_VIOLINES = 2  # los seis violines caben en UNA fila, de a dos por panel

    # El nombre con que cada violin se presenta en su eje x. Hace falta desde que van de a
    # dos por panel: con uno solo el titulo bastaba y la marca del eje lo repetia, asi que
    # estaba apagada. El nombre COMPLETO sigue en la etiqueta del mouse.
    NOMBRES_CORTOS_VIOLIN = {
        'prep': 'Lluvia', 'temp': 'Temperatura',
        'wind_gust_spd': 'Rafaga', 'wind_spd': 'Velocidad',
        'NR_T': 'Vegetacion', 'DDT': 'Descargas',
    }
    assert set(NOMBRES_CORTOS_VIOLIN) == set(VARS_VIOLIN)

    fig = make_subplots(
        # DOS filas. El mapa ocupaba dos y la serie una, asi que las dos piezas de la fila de
        # arriba no compartian ni el borde de abajo: el mapa bajaba hasta la mitad de la
        # figura y la serie se quedaba arriba, del tamanio de un cuarto. Con el mapa en una
        # sola fila las dos empiezan y acaban a la misma altura.
        #
        # Y los seis violines pasan de dos filas a UNA, de a dos por panel. La figura pierde
        # con eso una fila entera -- de 2.100 px a 1.575 -- y cada violin queda mas angosto,
        # que es el precio: lo que un violin dice es su FORMA, y esa se lee igual en 140 px
        # que en 300.
        rows=2, cols=VIOL_COLS,
        # El reparto sale de la FORMA del mapa: con 0.63 su recuadro queda casi cuadrado --
        # 476 px de alto para 470 de ancho -- en vez de una tira alta y angosta, y lo que
        # deja de gastar ahi lo gana la fila de violines, que sube.
        row_heights=[0.63, 0.37],
        vertical_spacing=0.16, horizontal_spacing=0.16,
        specs=[[{'type': 'map', 'colspan': 2}, None,
                {'secondary_y': True}],
               # Los tres paneles de violines declaran `secondary_y` aunque uno no lo use:
               # un eje secundario no se puede agregar despues de armar la rejilla.
               [{'secondary_y': True}, {'secondary_y': True}, {'secondary_y': True}]],
        # Los titulos se asignan en orden de lectura SOBRE LAS CELDAS QUE LLEVAN SUBPLOT:
        # primero el mapa (1,1), luego la serie (1,3), y despues los TRES paneles de violines.
        subplot_titles=(
            ['UITI + nube variable elegida',
             'UITI vs mediana variable elegida']
            # Titulos CORTOS: a 1.512 px de ventana cada columna mide ~336 px y los titulos
            # largos de columnas vecinas se tocan.
            + ['Lluvia y temperatura', 'Viento', 'Vegetacion y descargas']
        ),
    )

    # Trazas 0-5: violines del circuito/dia inicial (sincronizados por JS despues), uno por
    # variable, cada uno con su PROPIO eje independiente. El ylabel lleva la UNIDAD DE
    # MEDIDA -- el nombre de la variable ya lo pone el titulo del subplot, asi que el eje no
    # lo repite.
    _violin_inicial = POR_CIRCUITO[CIRCUITO]['violinPorDia'][0]
    # Los violines van de a DOS por panel, en el orden de `VARS_VIOLIN`: el que hace par
    # ocupa el eje y de la DERECHA, porque las seis variables no comparten unidad y dos
    # escalas distintas en un solo eje se leen como si una fuera mas grande que la otra.
    #
    # Con una excepcion: la rafaga y la velocidad estan las dos en km/h. Ahi un eje propio
    # para cada una seria lo contrario de una ayuda -- dos escalas para la misma unidad
    # invitan a comparar alturas que no son comparables --, asi que ese par COMPARTE el eje
    # y se lee una contra la otra, que es justo lo que se quiere de esas dos.
    for _idx, _v in enumerate(VARS_VIOLIN):
        _fila = FILA_VIOLINES
        _col = _idx // 2 + 1
        _pareja = VARS_VIOLIN[_idx - 1 if _idx % 2 else _idx + 1]
        _secundario = bool(_idx % 2) and UNIDADES[_v] != UNIDADES[_pareja]
        # Corto: el rotulo va girado y en esta fila hay hasta cuatro en el mismo hueco.
        _matiz = '12h' if _v in VARS else 'vano'
        fig.add_trace(go.Violin(
            y=_violin_inicial[_idx], name=NOMBRES_CORTOS_VIOLIN[_v], showlegend=False,
            line=dict(color='rgba(90,15,20,0.85)', width=1),
            fillcolor=COLORES_VIOLIN[_idx], opacity=0.85,
            box_visible=True, meanline_visible=False, points=False, spanmode='hard',
            hovertemplate=f'{NOMBRES_VARS[_v]}: %{{y:,.2f}} {UNIDADES[_v]}<extra></extra>',
        ), row=_fila, col=_col, secondary_y=_secundario)
        # El matiz -- media de las 12 h anteriores al evento, o valor fijo del vano -- vive
        # aqui y no en el titulo: el eje y va girado, asi que crecer no le quita sitio a
        # nadie, mientras que en el titulo empujaba contra el de la columna de al lado.
        #
        # El rotulo se pinta del COLOR de su violin. Con dos por panel es lo que dice cual
        # de los dos ejes le corresponde a cual, y no hay otra forma de saberlo.
        if _secundario or _idx % 2 == 0:
            fig.update_yaxes(title_text=f'{UNIDADES[_v]} ({_matiz})',
                             title_font_size=FUENTE_EJE_VIOLIN,
                             title_font_color=COLORES_VIOLIN[_idx],
                             showgrid=not _secundario,
                             row=_fila, col=_col, secondary_y=_secundario)

    # La serie ocupa un tercio del ancho de la figura: 230 px a 1.280 px de ventana. Con la
    # fuente base de 18 sus cuatro marcas de fecha suman 300 px y se pisaban de dos en dos.
    # Bajar la letra a 12 no bastaba -- seguian tocandose 'Jan 2026' y 'Mar 2026' --, y la
    # respuesta correcta en un eje de fechas no es letra mas pequenia sino MENOS marcas: con
    # `dtick='M3'` son tres para una serie de siete meses, que es cuanta fecha hace falta.
    # `%b %y` y no `%b %Y`: la marca va inclinada, asi que lo que mide de ANCHO cuelga por
    # debajo del panel. Con 'Oct 2025' llegaba al titulo del panel de violines de abajo;
    # 'Oct 25' cuelga un 40% menos y el anio de cuatro cifras no aporta nada en una serie
    # de siete meses cuyo rango ya esta escrito en el panel de control.
    fig.update_xaxes(tickfont_size=12, dtick='M3', tickformat='%b %y', row=1, col=3)

    # Traza 6: estructura del circuito activo, en negro, siempre visible.
    fig.add_trace(go.Scattermap(
        lat=[], lon=[], mode='lines', name='Estructura del circuito', showlegend=False,
        line=dict(width=ANCHO_SIN_EVENTOS, color=COLOR_SIN_EVENTO),
        hovertext=[], hoverinfo='text',
    ), row=1, col=1)
    # Traza 7: la nube. UN SOLO trazo Scattermap de marcadores para todo el circuito
    # activo. `marker.color` lleva los VALORES CRUDOS de la variable y el color lo resuelve
    # Plotly con `colorscale` + `cmin`/`cmax` fijados sobre el dataset completo; el JS solo
    # manda numeros. `marker.opacity` es escalar de TRAZA en Scattermap -- que es justo lo
    # que se quiere, una opacidad constante para todos los puntos.
    # hoverinfo='text' -- a diferencia de un trazo puramente decorativo -- porque el hover de
    # la nube tiene que mostrar el valor de la variable activa EN LA HORA VIGENTE,
    # reconstruido por JS en cada cambio de hora/variable, nunca una foto vieja.
    #
    # Va ANTES de la capa de UITI. Sus circulos son de 78 px y se solapan entre vanos vecinos,
    # de modo que aunque cada uno sea muy tenue (NUBE_OPACIDAD), la suma de una decena de ellos
    # cubre por completo lo que quede debajo. Medido con una captura del mapa de DON23L13: con
    # la nube dibujada ENCIMA, el mapa no tenia NI UN pixel de los cuatro colores de la escala;
    # ocultandola aparecian 1.514. La capa de UITI es el dato principal del mapa, asi que va
    # arriba.
    _cfg_ini = NUBE_CFG[VARIABLE_CLIMA]
    fig.add_trace(go.Scattermap(
        lat=[], lon=[], mode='markers', name='Nube por vano (variable seleccionable)',
        showlegend=False,
        marker=dict(size=NUBE_TAM, color=[], colorscale=_cfg_ini['escala'],  # lista, no nombre
                    cauto=False, cmin=_cfg_ini['vmin'], cmax=_cfg_ini['vmax'],
                    opacity=NUBE_OPACIDAD, showscale=False),
        hovertext=[], hoverinfo='text',
    ), row=1, col=1)
    # Trazas 8-11: la capa de UITI acumulado del dia, una traza por clase de cuartil. Va al
    # DOBLE de ancho que antes, opaca y ENCIMA de la nube. El JS solo mete en estas trazas los
    # vanos que TIENEN eventos ese dia: un vano sin eventos, o que no aparece en la lista del
    # dia, no recibe ningun segmento aqui (queda solo su linea negra de estructura).
    for _clase, _color in zip(CLASES_MAPA, COLORES_MAPA):
        fig.add_trace(go.Scattermap(
            lat=[], lon=[], mode='lines', name=_clase, showlegend=False,
            line=dict(width=ANCHO_MAPA, color=_color), opacity=OPACIDAD_UITI,
            hovertext=[], hoverinfo='text',
        ), row=1, col=1)

    # Trazas 12-13: los equipos, DESPUES de la nube y de la capa de UITI. En MapLibre el orden
    # de las capas sigue el orden de las trazas, asi que dibujarlos antes los dejaba tapados por
    # los circulos de 78 px de la nube. Van al final para que transformadores e interruptores se
    # vean SIEMPRE, con sus colores habituales.
    for _nombre, _color, _tam in [('Transformadores', COLOR_TRAFO, TAM_TRAFO),
                                  ('Interruptores / switches', COLOR_SWITCH, TAM_SWITCH)]:
        fig.add_trace(go.Scattermap(
            lat=[], lon=[], mode='markers', name=_nombre, showlegend=False,
            marker=dict(size=_tam, color=_color),
            hovertext=[], hoverinfo='text',
        ), row=1, col=1)

    # Trazas 14-15: la serie de tiempo de la casilla (1,3), una por eje y. El eje IZQUIERDO
    # lleva el UITI total del circuito por dia; el DERECHO la mediana diaria de la variable
    # activa (color y unidad cambian con el <select>, los reescribe el JS). El tamaño de los
    # marcadores es un ARRAY: el punto del dia vigente va al triple.
    _dias_x = [_d['periodo'] for _d in POR_CIRCUITO[CIRCUITO]['dias']]
    fig.add_trace(go.Scatter(
        x=_dias_x, y=POR_CIRCUITO[CIRCUITO]['uitiTotalPorDia'],
        mode='lines+markers', name='UITI diario', showlegend=False,
        line=dict(color=COLOR_SERIE_UITI, width=2),
        marker=dict(color=COLOR_SERIE_UITI, size=[SERIE_TAM] * len(_dias_x)),
        hovertemplate='%{x}<br>UITI del dia: %{y:,.2f}<extra></extra>',
    ), row=1, col=3, secondary_y=False)
    fig.add_trace(go.Scatter(
        x=_dias_x, y=POR_CIRCUITO[CIRCUITO]['medianaPorDia'][VARIABLE_CLIMA],
        mode='lines+markers', name='Mediana de la variable', showlegend=False,
        line=dict(color=NUBE_CFG[VARIABLE_CLIMA]['hue'], width=2, dash='dot'),
        marker=dict(color=NUBE_CFG[VARIABLE_CLIMA]['hue'], size=[SERIE_TAM] * len(_dias_x)),
        hovertemplate='%{x}<br>Mediana: %{y:,.2f}<extra></extra>',
    ), row=1, col=3, secondary_y=True)
    fig.update_yaxes(title_text='UITI del dia', title_font_size=FUENTE_EJE_TITULO,
                     color=COLOR_SERIE_UITI, row=1, col=3, secondary_y=False)
    fig.update_yaxes(title_text=f'{NOMBRES_VARS[VARIABLE_CLIMA]} ({UNIDADES[VARIABLE_CLIMA]})',
                     title_font_size=FUENTE_EJE_TITULO,
                     color=NUBE_CFG[VARIABLE_CLIMA]['hue'],
                     showgrid=False,  # dos rejillas superpuestas en la misma casilla ensucian
                     row=1, col=3, secondary_y=True)

    fig.update_layout(
        map=dict(style='carto-positron', center=dict(lat=5.07, lon=-75.52), zoom=10),
        title=dict(
            text=f'Nube por vano -- {CIRCUITO}',
            x=0.5, xanchor='center', yref='container',
            y=1 - TITULO_DESDE_ARRIBA_PX / ALTO_FIGURA, yanchor='top',
            font=dict(size=FUENTE_TITULO),
        ),
        legend=dict(title_text='', orientation='h', x=0.5, xanchor='center', y=1.02, yanchor='bottom',
                    font=dict(size=FUENTE_BASE)),
        font=dict(size=FUENTE_BASE),           # fuente por defecto de TODA la figura
        hoverlabel=dict(font_size=FUENTE_BASE),
        # Margenes al doble tambien: con el texto duplicado, los de antes recortaban el
        # titulo de la figura y los ylabel.
        margin=dict(t=105, r=90, b=80, l=MARGEN_IZQ_FIGURA),
        # SIN `width`: con un ancho fijo Plotly ignora el tamaño del contenedor y el panel
        # no puede aprovechar la pantalla. Dejandolo en None, `config.responsive` + un div al
        # 100% hacen que la figura se estire tanto en la celda del cuaderno como en el
        # navegador, y que se reajuste al cambiar el tamaño de la ventana. El alto SI queda
        # fijo: el subplot de mapa necesita una altura concreta para no colapsar.
        height=ALTO_FIGURA, template='plotly_white', violingap=0.3,
    )
    # Ticks de los dos ejes de cada violin, tambien al doble.
    fig.update_xaxes(tickfont_size=FUENTE_BASE)
    fig.update_yaxes(tickfont_size=FUENTE_BASE)
    # Menos en la fila de los violines: sus seis ejes se reparten dos huecos entre paneles,
    # y con la fuente base de 18 las marcas de un panel llegaban al rotulo del de al lado.
    fig.update_yaxes(tickfont_size=FUENTE_MARCA_VIOLIN, row=FILA_VIOLINES)
    fig.update_yaxes(tickfont_size=FUENTE_MARCA_VIOLIN, row=FILA_VIOLINES,
                     secondary_y=True)
    assert fig.layout.width is None, (
        'la figura no puede llevar ancho fijo: rompe el modo responsive del navegador')
    # Los titulos de subplot son anotaciones, no heredan `layout.font`: hay que fijarlos.
    for _a in fig.layout.annotations:
        _a.font.size = FUENTE_SUBTITULO
        # Diez px mas arriba. La marca mas alta de cada eje se dibuja CENTRADA en su
        # posicion, asi que la mitad sobresale por encima del panel -- exactamente donde
        # plotly pone este titulo. Medido: '90k' se montaba sobre el de la serie.
        _a.yshift = 10


    def _clave_eje(traza, cual):
        ref = getattr(traza, f'{cual}axis') or cual
        return f'{cual}axis' + ref[1:]


    _N_VIOL = len(VARS_VIOLIN)
    IDX = {
        'violines': list(range(_N_VIOL)),
        # Orden de dibujado en el mapa: estructura -> nube -> clases de UITI -> equipos.
        # En MapLibre el orden de las trazas ES el z-order de las capas. La nube va debajo de la
        # capa de UITI porque la tapaba por completo, y los equipos ULTIMOS para que no los tape
        # a ellos.
        'mapaSinEventos': _N_VIOL,
        'nube': _N_VIOL + 1,
        'mapaClases': [_N_VIOL + 2 + i for i in range(len(CLASES_MAPA))],
        'mapaTrafos': _N_VIOL + 2 + len(CLASES_MAPA),
        'mapaSwitches': _N_VIOL + 3 + len(CLASES_MAPA),
        'serieUiti': _N_VIOL + 4 + len(CLASES_MAPA),
        'serieVar': _N_VIOL + 5 + len(CLASES_MAPA),
    }
    EJES = {
        'violin': [_clave_eje(fig.data[i], 'y') for i in IDX['violines']],
        # El eje DERECHO se retitula y recolorea desde el JS cada vez que cambia la variable.
        'serieDer': _clave_eje(fig.data[IDX['serieVar']], 'y'),
    }

    # --- Invariante de trazas fijas (14) -------------------------------------------------
    assert len(fig.data) == _N_VIOL + 1 + len(CLASES_MAPA) + 2 + 1 + 2 == 16, len(fig.data)
    assert all(fig.data[i].type == 'violin' for i in IDX['violines'])
    # CINCO ejes para seis violines: los tres paneles aportan su eje izquierdo, y solo dos
    # de ellos un derecho. El par de viento comparte el suyo a proposito -- rafaga y
    # velocidad estan las dos en km/h --, y esa es toda la diferencia con 6.
    assert len(set(EJES['violin'])) == 5, 'el reparto de ejes de los violines cambio'
    assert EJES['violin'][2] == EJES['violin'][3], (
        'rafaga y velocidad comparten unidad, asi que tienen que compartir eje')
    # El ylabel de cada violin lleva su unidad de medida y, entre parentesis, de que numero
    # se trata: la media de las 12 h anteriores al evento, o el valor fijo del vano. Corto,
    # porque en esta fila hay hasta cuatro rotulos girados disputandose el mismo hueco.
    #
    # Rafaga y velocidad comparten eje -- las dos en km/h --, asi que su rotulo se escribe una
    # sola vez; la lista lo repite porque las dos entradas apuntan al MISMO eje.
    assert [fig.layout[_e].title.text for _e in EJES['violin']] == [
        f'{UNIDADES[_v]} ({"12h" if _v in VARS else "vano"})' for _v in VARS_VIOLIN]
    assert all(fig.data[i].type == 'scattermap'
               for i in IDX['mapaClases'] + [IDX['mapaSinEventos'], IDX['mapaTrafos'],
                                             IDX['mapaSwitches'], IDX['nube']])
    assert [fig.data[i].line.color for i in IDX['mapaClases']] == COLORES_MAPA
    assert (fig.data[IDX['mapaSinEventos']].line.width == ANCHO_SIN_EVENTOS
            and fig.data[IDX['mapaSinEventos']].line.color == COLOR_SIN_EVENTO)
    assert all(fig.data[i].line.width == ANCHO_MAPA == 7.0 for i in IDX['mapaClases']), (
        'capa de UITI: ancho al doble del original (3.5 -> 7.0)')
    # Opaca a proposito: es lo que hace que el color del mapa sea el MISMO que la muestra de la
    # leyenda del panel. A media tinta el fondo se mezclaba y la escala dejaba de leerse.
    assert all(fig.data[i].opacity == OPACIDAD_UITI == 1.0 for i in IDX['mapaClases']), (
        'capa de UITI: opaca, para que el color pintado sea el color umbralizado de la leyenda')
    # Z-ORDER. En MapLibre el orden de las trazas es el orden de las capas, y la nube tapaba la
    # capa de UITI: medido sobre DON23L13, con la nube encima el mapa no mostraba ni un pixel de
    # los cuatro colores de la escala, y ocultandola aparecian 1.514. Si alguien vuelve a mover
    # la nube detras de las clases, esto falla al generar y no en el navegador.
    assert IDX['nube'] < min(IDX['mapaClases']), (
        'la nube debe dibujarse DEBAJO de la capa de UITI o la tapa por completo')
    assert max(IDX['mapaClases']) < IDX['mapaTrafos'] < IDX['mapaSwitches'], (
        'los equipos van al final para que ni la nube ni la capa de UITI los tapen')
    # El tono de cada violin sale de la escala de SU variable, no de una paleta aparte.
    assert [fig.data[i].fillcolor for i in IDX['violines']] == [TONO_POR_VAR[_v] for _v in VARS_VIOLIN]
    assert fig.data[IDX['serieVar']].line.color == TONO_POR_VAR[VARIABLE_CLIMA], (
        'la serie derecha usa el mismo tono que el violin y la nube de su variable')
    assert fig.data[IDX['nube']].mode == 'markers'
    assert fig.data[IDX['nube']].marker.size == NUBE_TAM == 78, 'nube: circulos 3x (26 -> 78)'
    assert isinstance(fig.data[IDX['nube']].marker.color, (list, tuple)), (
        'nube: marker.color debe ser un array, ahora con los VALORES crudos por punto')
    assert fig.data[IDX['nube']].marker.opacity == NUBE_OPACIDAD == 0.4, (
        'nube: opacidad constante 0.4 para todos los puntos')
    assert IDX['nube'] < IDX['mapaTrafos'] < IDX['mapaSwitches'], (
        'los equipos se dibujan DESPUES de la nube, o quedan tapados por sus circulos')
    assert (fig.data[IDX['mapaTrafos']].marker.color, fig.data[IDX['mapaTrafos']].marker.size) == (COLOR_TRAFO, TAM_TRAFO)
    assert (fig.data[IDX['mapaSwitches']].marker.color, fig.data[IDX['mapaSwitches']].marker.size) == (COLOR_SWITCH, TAM_SWITCH)
    assert fig.data[IDX['nube']].marker.colorscale is not None, (
        'nube: el valor se codifica con color, via colorscale + cmin/cmax')
    assert not isinstance(fig.data[IDX['nube']].marker.colorscale, str), (
        'nube: la colorscale tiene que ir RESUELTA como lista de pares -- plotly.js no conoce '
        'los nombres de ColorBrewer (OrRd/BuGn/Oranges) y cae en silencio a RdBu')
    assert fig.data[IDX['nube']].marker.cauto is False, (
        'nube: con cauto=True Plotly ignora cmin/cmax y reescala al rango del dia')
    assert (fig.data[IDX['nube']].marker.cmin, fig.data[IDX['nube']].marker.cmax) == RANGO_GLOBAL[VARIABLE_CLIMA], (
        'nube: cmin/cmax se fijan sobre el dataset completo, no por circuito')
    assert fig.data[IDX['nube']].hoverinfo == 'text', (
        'nube: el hover tiene que mostrar el valor activo por punto, no un hover generico')
    assert len(CIRCUITOS) > 0
    assert (LAG_MAX + 1) == 25
    # --- Invariante de tipografia -------------------------------------------------------
    # Estaba al DOBLE de la version original, elegido cuando la figura ocupaba el ancho
    # entero de la pantalla. Con el tablero en dos columnas la figura se queda con el 70%, y
    # a 1.512 px cada una de las tres columnas de violines mide 336 px: con 24 px de fuente
    # los titulos de columnas vecinas se tocaban, y las marcas de un panel chocaban con el
    # rotulo del de al lado. La escala baja en la misma proporcion que el ancho, ~0,78.
    assert (FUENTE_BASE, FUENTE_SUBTITULO, FUENTE_EJE_TITULO, FUENTE_TITULO) == (18, 19, 17, 27)
    assert fig.layout.font.size == FUENTE_BASE
    assert all(_a.font.size == FUENTE_SUBTITULO for _a in fig.layout.annotations)
    assert all(fig.layout[_e].tickfont.size == FUENTE_MARCA_VIOLIN for _e in EJES['violin'])
    # --- Invariante de la serie de tiempo -----------------------------------------------
    assert fig.data[IDX['serieUiti']].type == 'scatter' and fig.data[IDX['serieVar']].type == 'scatter'
    assert EJES['serieDer'] != _clave_eje(fig.data[IDX['serieUiti']], 'y'), (
        'las dos series tienen que caer en ejes y DISTINTOS (doble eje)')
    assert (len(fig.data[IDX['serieUiti']].x) == len(fig.data[IDX['serieVar']].x)
            == len(POR_CIRCUITO[CIRCUITO]['dias'])), 'un punto por dia en ambas series'
    assert all(isinstance(fig.data[i].marker.size, (list, tuple)) for i in
               (IDX['serieUiti'], IDX['serieVar'])), (
        'marker.size debe ser un array: el punto del dia vigente va al triple')
    assert SERIE_TAM_ACTIVO == SERIE_TAM * 3
    # --- Invariante de la grilla 2x3 ----------------------------------------------------
    # Fila 1: el mapa en (1,1) estirado sobre dos columnas -- por eso (1,2) no lleva subplot
    # propio -- y la serie en (1,3), a la MISMA altura que el mapa, que es de lo que se trata.
    # Fila 2: los tres paneles de violines, los tres con dos ejes y aunque el del viento use
    # uno solo.
    assert len(fig._grid_ref) == 2 and all(len(_f) == VIOL_COLS for _f in fig._grid_ref)
    assert fig._grid_ref[0][1] is None, '(1,2) la cubre el colspan del mapa'
    assert fig._grid_ref[0][2] is not None and len(fig._grid_ref[0][2]) == 2, (
        '(1,3) lleva la serie de tiempo, con DOS ejes y (secondary_y)')
    assert all(_celda is not None and len(_celda) == 2 for _celda in fig._grid_ref[1]), (
        'los tres paneles de violines llevan dos ejes y cada uno')

    print(f'{len(fig.data)} trazas en una grilla 2x{VIOL_COLS}: mapa sobre dos columnas en '
          f'(1,1)-(1,2) -- 1 estructura + {len(CLASES_MAPA)} clases UITI + 2 equipos + 1 nube --, '
          f'serie de tiempo de doble eje en (1,3) (2 trazas), y {_N_VIOL} violines de a dos '
          f'en los tres paneles de la fila 2')
    print(f'serie (1,3): eje izq = UITI total del circuito por dia, eje der = {EJES["serieDer"]} '
          f'= mediana diaria de la variable activa | punto del dia vigente {SERIE_TAM} -> '
          f'{SERIE_TAM_ACTIVO} px (x3)')
    print(f'nube: {len(VARS_VIOLIN)} variables elegibles desde el <select> '
          f'({len(VARS)} climaticas + {len(VARS_ESTATICAS)} estaticas)')
    print(f'tipografia al doble: base/subtitulo {FUENTE_BASE}, ylabel {FUENTE_EJE_TITULO}, '
          f'titulo {FUENTE_TITULO} | alto de la figura {ALTO_FIGURA} px')
    print('ejes de los violines (independientes):', EJES['violin'])
    print('unidades en el ylabel:', {_v: UNIDADES[_v] for _v in VARS_VIOLIN})
    print(f'{len(CIRCUITOS)} circuitos elegibles en vivo desde el <select> del panel | '
          f'25 horas de rezago (0..24) en el slider de la nube | circulos de la nube: {NUBE_TAM} px')

    DIV_FIGURA = 'clima-nube-vano'

    # CTX.porCircuito trae los 208 circuitos: el panel cambia de circuito EN VIVO leyendo
    # esta estructura, sin volver a ejecutar Python.
    CONTEXTO = {
        'div': DIV_FIGURA,
        # No viaja la lista de circuitos: el <select> ya se arma en Python mas abajo y el JS
        # nunca la leia.
        'porCircuito': {
            _c: {
                'dias': _cc['dias'],
                'fidsPorDia': _cc['fidsPorDia'],
                'uitiPorDia': _cc['uitiPorDia'],
                'nubePorDia': _cc['nubePorDia'],
                'violinPorDia': _cc['violinPorDia'],
                'uitiTotalPorDia': _cc['uitiTotalPorDia'],
                'medianaPorDia': _cc['medianaPorDia'],
                'umbrales': _cc['umbrales'],
                'rotulos': _cc['rotulos'],
                'geo': _cc['geo'],
                'trafos': _cc['trafos'],
                'switches': _cc['switches'],
            }
            for _c, _cc in POR_CIRCUITO.items()
        },
        # La paleta va en la RAIZ, no dentro de cada circuito: las series se repiten tambien
        # ENTRE circuitos, y replicarla por circuito devolveria justo el peso que se quito.
        'nubePaleta': NUBE_PALETA,
        'nubeCfg': NUBE_CFG,
        'variables': [{'codigo': _v, 'nombre': NOMBRES_VARS[_v],
                       'estatica': _v in VARS_ESTATICAS} for _v in VARS_VIOLIN],
        'varDefaultIdx': VARS_VIOLIN.index(VARIABLE_CLIMA),
        'clases': CLASES_MAPA,
        'colores': COLORES_MAPA,
        'horasLabels': list(range(LAG_MAX + 1)),
        'serieTam': SERIE_TAM,
        'serieTamActivo': SERIE_TAM_ACTIVO,
        'idx': IDX,
        'ejes': EJES,
        'defaultCircuito': CIRCUITO,
    }
    assert set(CONTEXTO['porCircuito'].keys()) == set(CIRCUITOS)
    assert CONTEXTO['defaultCircuito'] in CONTEXTO['porCircuito']
    assert [v['codigo'] for v in CONTEXTO['variables']] == VARS_VIOLIN, (
        'el <select> de la nube tiene que ofrecer las 6 variables, en el orden de VARS_VIOLIN')
    assert set(CONTEXTO['nubeCfg']) == set(VARS_VIOLIN)
    assert set(CONTEXTO['nubePaleta']) == set(VARS_VIOLIN), (
        'cada variable de la nube necesita su paleta de series')
    assert all('nubePaleta' not in _cc for _cc in CONTEXTO['porCircuito'].values()), (
        'la paleta viaja UNA vez en la raiz, no replicada en los 208 circuitos')
    assert all('nubeCfgPorVar' not in _cc for _cc in CONTEXTO['porCircuito'].values()), (
        'el cfg de la nube viaja UNA vez en la raiz, no replicado en los 208 circuitos')

    _opciones_circuito = ''.join(
        f'<option value="{c}"{" selected" if c == CIRCUITO else ""}>{c}</option>'
        for c in CIRCUITOS)
    # El <select> de la nube ofrece LAS 6: las 4 climaticas por rezago horario y las 2
    # estaticas del vano, agrupadas aparte para dejar claro que el slider de hora no las
    # mueve.
    _opciones_variable = (
        '<optgroup label="Climaticas (por rezago horario)">' +
        ''.join(f'<option value="{v}"{" selected" if v == VARIABLE_CLIMA else ""}>'
                f'{NOMBRES_VARS[v]}</option>' for v in VARS) +
        '</optgroup><optgroup label="Estaticas del vano (sin rezago)">' +
        ''.join(f'<option value="{v}"{" selected" if v == VARIABLE_CLIMA else ""}>'
                f'{NOMBRES_VARS[v]}</option>' for v in VARS_ESTATICAS) +
        '</optgroup>')

    # Mismo estilo de panel (tema rojo) que 03/04 y que la version anterior de este
    # cuaderno: borde/acento rgb(203,24,29), fondo/texto neutros -- sin ningun azul.
    PANEL_HTML = f'''
<style>
  .panel-clima {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 24px;
    display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end;
    max-width: 100%; margin: 0 0 6px 0; padding: 12px 14px; box-sizing: border-box;
    border: 1px solid #e4c4c0; border-left: 4px solid rgb(203,24,29);
    border-radius: 6px; background: #fdf7f6; color: #2b2b2b;
  }}
  .panel-clima label {{ display: block; font-weight: 600; margin-bottom: 8px; }}
  .panel-clima select {{
    font: inherit; padding: 8px 12px; border: 1px solid #c9a9a5;
    border-radius: 4px; background: #fff; color: #2b2b2b; min-width: 280px;
  }}
  /* Los sliders tambien crecen: con texto de 26 px una barra de 4 px se pierde. */
  .panel-clima input[type="range"] {{ height: 28px; }}
  .panel-clima button {{
    font: inherit; font-weight: 600; padding: 6px 14px; cursor: pointer;
    border: 1px solid rgb(203,24,29); border-radius: 4px;
    background: rgb(203,24,29); color: #fff;
  }}
  .panel-clima button:hover {{ background: rgb(165,15,21); }}
  .panel-aviso {{
    flex-basis: 100%; font-size: 22px; color: #7a5c58; margin: 0; font-weight: 400;
  }}
  #cl-info {{
    flex-basis: 100%; font-size: 23px; color: #2b2b2b; margin: 0; padding: 12px 16px;
    background: #fdf7f6; border: 1px solid #e4c4c0; border-radius: 4px;
  }}
  /* Sin detalle que mostrar no hay caja: ni recuadro, ni relleno, ni sitio ocupado. */
  #cl-info:empty {{ display: none; }}
</style>
<style>
  /* La barra del boton de encuadre, ENCIMA del mapa y alineada con el, como en el
     simulador. Su relleno izquierdo es el margen de la figura: ahi es donde empieza el
     mapa dentro del recuadro de plotly. */
  /* Los 12 px de abajo no son estetica: con 2 el pie del boton caia 7 px dentro del
     titulo de la figura -- medido a 1.280 y 1.512 px, donde el titulo centrado llega
     hasta debajo del boton; a 1.900 ya no se cruzan. */
  .barra-encuadre {{ padding: 0 0 0 {MARGEN_IZQ_FIGURA}px; margin: 0 0 12px 0; }}
  /* Y el estilo es el del boton del simulador, medido en el navegador sobre la
     aplicacion servida: es un `widgets.Button` sin `button_style`, o sea el gris por
     defecto de Jupyter. Aqui hay que escribirlo porque este tablero es HTML estatico y
     no trae la hoja de estilos de los widgets. */
  .barra-encuadre button {{
    font-family: Arial, sans-serif; font-size: 13px; font-weight: 400;
    color: rgba(0, 0, 0, 0.87); background: rgb(238, 238, 238);
    border: 0; border-radius: 2px; padding: 0 10px;
    width: 260px; height: 28px; line-height: 28px; margin: 2px;
    text-align: center; cursor: pointer;
  }}
  .barra-encuadre button:hover {{ background: rgb(224, 224, 224); }}
</style>
<div class="panel-clima">
  <div><label for="cl-circuito">Circuito</label>
       <select id="cl-circuito">{_opciones_circuito}</select></div>
  <div><label for="cl-variable">Variable de la nube</label>
       <select id="cl-variable">{_opciones_variable}</select></div>
  <div style="flex-basis:100%; font-size:21px; display:flex; flex-wrap:wrap;
              gap:8px 28px; align-items:center; color:#5b4a48;">
    <span style="font-weight:600;">Escala de la nube (variable activa):</span>
    <span id="cl-nube-escala"></span>
  </div>
  <div style="flex-basis:100%; display:flex; align-items:center; gap:10px;">
    <label for="cl-dia" id="cl-dia-lbl" style="margin:0; white-space:nowrap;">Dia</label>
    <input type="range" id="cl-dia" min="0" max="{len(POR_CIRCUITO[CIRCUITO]['dias']) - 1}" value="0" step="1"
           style="flex:1; accent-color: rgb(203,24,29);">
    <span id="cl-dia-txt" style="font-weight:600; white-space:nowrap; min-width:300px;"></span>
  </div>
  <div style="flex-basis:100%; display:flex; align-items:center; gap:10px;">
    <label for="cl-hora" id="cl-hora-lbl" style="margin:0; white-space:nowrap;">
      Horas antes del evento (0 = hora del evento)</label>
    <input type="range" id="cl-hora" min="0" max="{LAG_MAX}" value="0" step="1"
           style="flex:1; accent-color: rgb(203,24,29);">
    <span id="cl-hora-txt" style="font-weight:600; white-space:nowrap; min-width:220px;"></span>
  </div>
  <div style="flex-basis:100%; font-size:21px; display:flex; flex-wrap:wrap;
              gap:8px 28px; align-items:center; color:#5b4a48;">
    <span style="font-weight:600;">Mapa (UITI diario, cortes por circuito):</span>
    <span id="cl-mapa-escala"></span>
    <span><span style="display:inline-block;width:40px;height:0;border-top:6px solid
      {COLOR_SIN_EVENTO};vertical-align:middle;margin-right:10px;"></span>Sin eventos</span>
    <span><span style="display:inline-block;width:18px;height:18px;background:{COLOR_TRAFO};
      border-radius:50%;margin-right:10px;"></span>Transformador</span>
    <span><span style="display:inline-block;width:18px;height:18px;background:{COLOR_SWITCH};
      border-radius:50%;margin-right:10px;"></span>Interruptor</span>
    <span style="font-weight:600; margin-left:20px;">Nube:</span>
    <span id="cl-nube-nombre"></span>
  </div>
  <p class="panel-aviso" id="cl-aviso"></p>
  <!-- Vacio a proposito: `#cl-info:empty` no ocupa nada. La caja tiene que seguir
       existiendo porque es donde el clic sobre la nube escribe el detalle del vano; si
       se borra, `getElementById('cl-info')` da null y el clic deja de hacer nada sin
       avisar. Lo que se quito es el texto de espera y el recuadro mientras no hay nada. -->
  <div id="cl-info"></div>
</div>
'''

    # El JS se arma con marcadores de texto, NO con % ni con f-string: el JSON de CTX trae
    # llaves y el JS trae "%" en varios sitios (border-radius:50%). .replace() por marcador
    # evita tener que escapar todo eso a mano (mismo patron que 03).
    PANEL_JS_TEMPLATE = r'''
<script type="text/javascript">
(function () {
  var CTX = __CTX_JSON__;
  var d = document;
  var CIRC = CTX.defaultCircuito;
  var VAR_ACTUAL = CTX.varDefaultIdx;
  var RECENTRADO = false;

  // Alineados punto a punto con la traza de la nube del dia/circuito actual:
  // DIA_FIDS[i] es el vano del punto i, DIA_SERIES[i] son sus 25 horas de rezago DE LA
  // VARIABLE ACTIVA. El slider de hora, el click y el hover los leen sin reconstruir
  // lat/lon.
  var DIA_SERIES = [];
  var DIA_FIDS = [];

  function C() { return CTX.porCircuito[CIRC]; }
  function varActualCodigo() { return CTX.variables[VAR_ACTUAL].codigo; }
  // El cfg de la nube NO depende del circuito: los cortes son globales del dataset, para
  // que un escalon de opacidad signifique lo mismo al cambiar de circuito.
  function cfgActual() { return CTX.nubeCfg[varActualCodigo()]; }

  function diaActual() {
    var el = d.getElementById('cl-dia');
    var v = el ? (parseInt(el.value, 10) || 0) : 0;
    return Math.max(0, Math.min(C().dias.length - 1, v));
  }

  function horaActual() {
    var el = d.getElementById('cl-hora');
    var v = el ? (parseInt(el.value, 10) || 0) : 0;
    return Math.max(0, Math.min(CTX.horasLabels.length - 1, v));
  }

  function claseDe(valor, umbrales) {
    if (!(valor > 0)) { return -1; }
    for (var i = 0; i < umbrales.length; i++) {
      if (valor <= umbrales[i]) { return i; }
    }
    return umbrales.length;
  }

  // Ya no hay ninguna cuenta de color en el JS: el valor va crudo a marker.color y
  // Plotly lo resuelve con colorscale + cmin/cmax. La opacidad es una constante de traza.

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
  var GEO_DENSO = {};              // cache por circuito: densificar una vez, no por dia

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

  function geoDenso(circ, geo) {
    if (GEO_DENSO[circ]) { return GEO_DENSO[circ]; }
    var la = [], lo = [], i, den;
    for (i = 0; i < geo.fids.length; i++) {
      den = densificar(geo.lat[i], geo.lon[i]);
      la.push(den[0]);
      lo.push(den[1]);
    }
    GEO_DENSO[circ] = {lat: la, lon: lo};
    return GEO_DENSO[circ];
  }

  // --- Encuadre del mapa ------------------------------------------------------------
  // fitBounds real en Web Mercator, no un zoom derivado del span en grados. Un grado de
  // latitud y uno de longitud no ocupan los mismos pixeles, y el mapa no tiene ancho fijo:
  // la figura se sirve al 100% del contenedor, de modo que su ancho lo decide la ventana
  // del navegador. Con la formula en grados el zoom salia igual a 1280 que a 2560 px, y el
  // circuito quedaba centrado pero mucho mas pequeno de lo que cabia. El zoom lo fija ahora
  // la dimension que se queda sin lugar primero, medida sobre el tamano real del lienzo.
  // Mismo criterio y mismas constantes que el 03 y el 04.
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
    // nula -- y nunca recorta un encuadre real. Con 15 saturaba el 22% de los circuitos a 2560 px (su mapa mide 842 px de alto), y saturar el techo es
    // volver al zoom fijo que este bloque vino a sustituir, justo en los circuitos
    // pequenos, que son los que mas necesitan acercarse.
    var escala = Math.min.apply(null, restricciones);
    return {center: {lat: (b[0] + b[1]) / 2, lon: (b[2] + b[3]) / 2},
            zoom: Math.min(17, Math.max(3, Math.log(escala) / Math.LN2))};
  }

  function encuadrarCircuito(gd) {
    var cc = C();
    if (!cc || !cc.geo || !cc.geo.bounds) { return; }
    var tam = tamanoMapa(gd);
    var vista = encuadre(cc.geo.bounds, tam[0], tam[1]);
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
      var aviso = d.getElementById('cl-aviso');
      if (aviso) {
        aviso.textContent = 'Ningun vano registro eventos en este periodo: el mapa se '
                          + 'encuadra sobre el circuito completo.';
      }
      encuadrarCircuito(gd);
      return;
    }
    var tam = tamanoMapa(gd);
    var vista = encuadre(b, tam[0], tam[1]);
    if (!vista) { return; }
    Plotly.relayout(gd, {'map.center': vista.center, 'map.zoom': vista.zoom});
  }

  (function () {
    var boton = d.getElementById('cl-centrar');
    if (!boton) { return; }
    boton.addEventListener('click', function () {
      var gd = d.getElementById(CTX.div);
      if (gd && gd._fullLayout) { encuadrarEventos(gd); }
    });
  })();

  function dibujarMapa(gd, diaIdx) {
    var cc = C();
    var dia = cc.dias[diaIdx];
    d.getElementById('cl-dia-txt').textContent = dia.etiqueta + ': ' + dia.periodo;

    var nClases = CTX.clases.length;
    var lat = [], lon = [], txt = [], i;
    for (i = 0; i < nClases; i++) { lat.push([]); lon.push([]); txt.push([]); }
    var elat = [], elon = [], etxt = [];

    // uitiPorDia viaja como ARRAY alineado a fidsPorDia (las llaves de vano se
    // serializaban antes una vez por variable y por dia: 5.7 MB de JSON repetido). El
    // diccionario que necesita el barrido de la geometria se arma aqui, una vez por dia.
    var fidsDia = cc.fidsPorDia[diaIdx] || [], uitiDia = cc.uitiPorDia[diaIdx] || [];
    var uiti = {};
    for (i = 0; i < fidsDia.length; i++) { uiti[fidsDia[i]] = uitiDia[i]; }
    var geo = cc.geo, den = geoDenso(CIRC, geo);
    for (i = 0; i < geo.fids.length; i++) {
      var fid = geo.fids[i], dato = uiti[fid];
      var valor = dato ? dato[0] : 0, n = dato ? dato[1] : 0;
      // Sin entrada en la lista del dia (`!dato`) o con UITI no positivo, el vano NO
      // entra en ninguna traza de la capa de UITI: c = -1 y el bloque de abajo lo salta.
      // Solo queda dibujado en negro por la traza de estructura.
      var c = dato ? claseDe(valor, cc.umbrales) : -1;
      var etiqueta = '<b>Vano ' + fid + '</b><br>' + dia.etiqueta + ': ' + dia.periodo +
                     '<br>UITI acumulado: ' + (dato ? valor.toLocaleString() : '0') +
                     '<br>Eventos: ' + n;
      // La etiqueta se repite en CADA vertice densificado: el hover engancha en el punto
      // mas cercano, y todos los del vano dicen lo mismo.
      var k, dLa = den.lat[i], dLo = den.lon[i];
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
      var oLa = geo.lat[i], oLo = geo.lon[i], ex, ie;
      for (ex = 0; ex < 2; ex++) {
        ie = ex === 0 ? 0 : oLa.length - 1;
        elat = elat.concat([oLa[ie], oLa[ie]], [null]);
        elon = elon.concat([oLo[ie] - MARCA_VANO, oLo[ie] + MARCA_VANO], [null]);
        etxt.push(etiqueta); etxt.push(etiqueta); etxt.push('');
      }
      if (c >= 0) {  // solo los vanos CON eventos ese dia reciben capa de UITI
        lat[c] = lat[c].concat(dLa, [null]);
        lon[c] = lon[c].concat(dLo, [null]);
        for (k = 0; k < dLa.length; k++) { txt[c].push(etiqueta); }
        txt[c].push('');
      }
    }
    var indices = [CTX.idx.mapaSinEventos].concat(CTX.idx.mapaClases);
    Plotly.restyle(gd, {lat: [elat].concat(lat), lon: [elon].concat(lon),
                        hovertext: [etxt].concat(txt)}, indices);

    var tr = cc.trafos, sw = cc.switches;
    var trTxt = tr.lat.map(function () { return '<b>Transformador</b><br>Circuito: ' + CIRC; });
    var swTxt = sw.lat.map(function () { return '<b>Interruptor / switch</b><br>Circuito: ' + CIRC; });
    Plotly.restyle(gd, {lat: [tr.lat, sw.lat], lon: [tr.lon, sw.lon],
                        hovertext: [trTxt, swTxt]}, [CTX.idx.mapaTrafos, CTX.idx.mapaSwitches]);

    // Recentrar SOLO al cambiar de circuito: si el usuario se acerco a una zona y mueve
    // el slider de dia, volver a encuadrar descartaria el zoom que eligio. El dia repinta
    // colores, no cambia de circuito. `cambiarCircuito` reinicia la bandera.
    if (!RECENTRADO && geo.bounds) {
      RECENTRADO = true;
      encuadrarCircuito(gd);
    }
  }

  // Reconstruye los puntos de la nube para el dia/circuito elegido, DE LA VARIABLE
  // ACTIVA: un punto por vano con datos climaticos ese dia, ubicado en su centroide.
  // Cachea la serie horaria de cada punto y delega el color/hover en pintarNube.
  function construirNube(gd, diaIdx) {
    var cc = C();
    // fidsPorDia y nubePorDia[var] estan alineados posicion a posicion, asi que basta un
    // recorrido por indice -- sin Object.keys y sin volver a mirar las llaves.
    // nubePorDia ya no trae la serie sino su POSICION en CTX.nubePaleta[var]: las series
    // climaticas se repiten ~13x entre vanos vecinos, asi que viajan una sola vez.
    var fids = cc.fidsPorDia[diaIdx] || [];
    var paleta = CTX.nubePaleta[varActualCodigo()] || [];
    var series = (cc.nubePorDia[varActualCodigo()] || [])[diaIdx] || [];
    var centros = cc.geo.centros;
    var lats = [], lons = [], i, centro;
    DIA_SERIES = [];
    DIA_FIDS = [];
    for (i = 0; i < fids.length; i++) {
      centro = centros[fids[i]];
      if (!centro) { continue; }
      lats.push(centro[0]);
      lons.push(centro[1]);
      DIA_SERIES.push(paleta[series[i]]);
      DIA_FIDS.push(fids[i]);
    }
    Plotly.restyle(gd, {lat: [lats], lon: [lons]}, [CTX.idx.nube]);
    return pintarNube(gd);
  }

  // Restyle de marker.color Y hovertext JUNTOS, por punto: el hover y el click de la
  // nube siempre tienen que mostrar el valor de LA HORA VIGENTE, nunca una foto vieja
  // -- por eso esto se llama tanto al mover el slider de hora como al cambiar de
  // variable (via construirNube), y no solo al cambiar de dia/circuito.
  // NR_T y DDT son atributos ESTATICOS del vano: su serie viaja con UN solo valor, no
  // con 25 rezagos (repetirlo 25 veces inflaria el JSON ~50% sin decir nada nuevo). Por
  // eso se indexa con clamp -- misma ruta de codigo para los dos casos -- y el slider de
  // hora se deshabilita mientras una estatica este activa.
  function pintarNube(gd) {
    var hora = horaActual();
    var cfg = cfgActual();
    var etHora = cfg.estatica ? 'no aplica'
      : (CTX.horasLabels[hora] === 0 ? '0 (evento)' : CTX.horasLabels[hora] + ' h antes');
    d.getElementById('cl-hora-txt').textContent = etHora;
    var etHoraLarga = cfg.estatica ? 'atributo estatico del vano (no varia por hora)'
      : (CTX.horasLabels[hora] === 0 ? 'hora del evento' : CTX.horasLabels[hora] + ' h antes');
    var valores = [], hovers = [], i, valor;
    for (i = 0; i < DIA_SERIES.length; i++) {
      valor = DIA_SERIES[i][Math.min(hora, DIA_SERIES[i].length - 1)];
      valores.push(valor);
      hovers.push('<b>Vano ' + DIA_FIDS[i] + '</b><br>' + cfg.nombre + ': ' +
        valor.toLocaleString() + ' ' + cfg.unidad + '<br>' + etHoraLarga);
    }
    // La escala y los cortes viajan en el MISMO restyle que los valores: si se mandaran
    // aparte, un cambio de variable pintaria un instante los valores nuevos con la escala
    // vieja.
    return Plotly.restyle(gd, {
      'marker.color': [valores], 'hovertext': [hovers],
      'marker.colorscale': [cfg.escala],
      // cauto explicito en CADA restyle: si Plotly lo deja en auto, ignora cmin/cmax y
      // reescala al rango DEL DIA, con lo que un color dejaria de significar el mismo
      // valor entre dias y entre circuitos.
      'marker.cauto': false, 'marker.cmin': cfg.vmin, 'marker.cmax': cfg.vmax,
      'marker.opacity': cfg.opacidad,
    }, [CTX.idx.nube]);
  }

  function escalaMapaHtml(cc) {
    // Cada recuadro y su texto van dentro de UN `inline-block`, que es una sola pieza
    // para el flex de afuera. Sueltos, con el panel en una columna del 30%, la tira se
    // partia ENTRE los dos y cada rotulo quedaba junto al color del siguiente: una
    // leyenda que miente, peor que una que se sale del recuadro.
    var out = '<span style="display:inline-flex;gap:2px;align-items:center;">';
    for (var i = 0; i < CTX.clases.length; i++) {
      out += '<span style="display:inline-block;margin-right:16px;">' +
             '<span style="display:inline-block;width:40px;height:20px;background:' +
             CTX.colores[i] + ';vertical-align:middle;"></span>' +
             '<span style="font-size:18px;color:#7a5c58;vertical-align:middle;">' +
             CTX.clases[i] + ' (' + cc.rotulos[i] + ')</span></span>';
    }
    return out + '</span>';
  }

  // Muestras de la escala, ya resueltas en Python (cfg.muestras = pares [valor, color]).
  // Se pintan con la MISMA opacidad de la nube, para que la tira no prometa un color mas
  // saturado del que se ve en el mapa.
  function escalaNubeHtml(cfg) {
    var partes = [], i, valor, color;
    for (i = 0; i < cfg.muestras.length; i++) {
      valor = cfg.muestras[i][0];
      color = cfg.muestras[i][1];
      // El par va junto, por lo mismo que en `escalaMapaHtml`: si la tira se parte
      // entre el recuadro y su numero, cada valor queda junto al color equivocado.
      partes.push(
        '<span style="display:inline-block;margin-right:16px;">' +
        '<span style="display:inline-block;width:40px;height:20px;border:1px solid #e4c4c0;' +
        'background:' + color + ';opacity:' + cfg.opacidad + ';vertical-align:middle;"></span>' +
        '<span style="font-size:18px;color:#7a5c58;vertical-align:middle;">' +
        valor.toFixed(1) + '</span></span>'
      );
    }
    return '<span style="display:inline-flex;gap:2px;align-items:center;">' + partes.join('') + '</span>';
  }

  // Refleja el circuito/variable activos en todas las etiquetas del panel -- nombre,
  // rango, escala de la nube, escala de cuartiles de UITI (propia de cada circuito) --
  // y resincroniza ambos <select> por si el cambio vino de otro lado.
  function actualizarEtiquetas() {
    var cfg = cfgActual(), cc = C();
    d.getElementById('cl-nube-nombre').textContent = cfg.nombre;
    // El rango global de la variable ya no se escribe en el panel: la tira de escala de
    // abajo lo dice con sus propios numeros, del primero al ultimo. Si vuelve el texto,
    // tiene que volver TAMBIEN su <span id="cl-nube-rango"> -- sin el, esta linea daba
    // null y el panel se quedaba sin actualizar ninguna etiqueta, en silencio.
    d.getElementById('cl-nube-escala').innerHTML = escalaNubeHtml(cfg);
    d.getElementById('cl-mapa-escala').innerHTML = escalaMapaHtml(cc);
    // El slider de DIA solo tiene sentido si el circuito registra mas de un dia con
    // eventos. 12 de los 208 registran exactamente uno (DOR23L12, por ejemplo, tiene 26
    // filas y todas del 2025-11-03) y 39 tienen tres o menos. Sin este trato el control
    // queda habilitado pero no se mueve, y la serie de tiempo dibuja un unico punto: las
    // dos cosas se leen como un tablero roto cuando en realidad son el dato. La etiqueta
    // lleva ademas el conteo, para que el numero de dias sea visible antes de arrastrar.
    var nDias = C().dias.length;
    var sliderD = d.getElementById('cl-dia');
    if (sliderD) {
      sliderD.disabled = nDias <= 1;
      sliderD.style.opacity = nDias <= 1 ? '0.35' : '';
    }
    var etiquetaD = d.getElementById('cl-dia-lbl');
    if (etiquetaD) {
      etiquetaD.textContent = nDias <= 1
        ? 'Dia -- ' + CIRC + ' registra eventos en un solo dia'
        : 'Dia (' + nDias + ' con eventos)';
      etiquetaD.style.opacity = nDias <= 1 ? '0.5' : '';
    }

    // El slider de hora solo tiene sentido para las climaticas: con una estatica activa
    // se deshabilita en vez de quedar mintiendo que mueve algo.
    var sliderH = d.getElementById('cl-hora');
    if (sliderH) {
      sliderH.disabled = !!cfg.estatica;
      sliderH.style.opacity = cfg.estatica ? '0.35' : '';
    }
    var etiquetaH = d.getElementById('cl-hora-lbl');
    if (etiquetaH) {
      etiquetaH.textContent = cfg.estatica
        ? 'Horas antes del evento -- no aplica a ' + cfg.nombre
        : 'Horas antes del evento (0 = hora del evento)';
      etiquetaH.style.opacity = cfg.estatica ? '0.5' : '';
    }
    var selV = d.getElementById('cl-variable');
    if (selV && selV.value !== varActualCodigo()) { selV.value = varActualCodigo(); }
    var selC = d.getElementById('cl-circuito');
    if (selC && selC.value !== CIRC) { selC.value = CIRC; }
  }

  // Son 6 violines (4 climaticos + vegetacion + DDT) de a dos en tres paneles. El
  // fallback se arma desde CTX.idx.violines para que agregar o quitar una variable en
  // Python no deje aqui un largo viejo hardcodeado.
  function dibujarViolines(gd, diaIdx) {
    var arrs = C().violinPorDia[diaIdx] ||
               CTX.idx.violines.map(function () { return []; });
    Plotly.restyle(gd, {y: arrs}, CTX.idx.violines);
  }

  // Casilla (2,3): las dos series de tiempo. El eje IZQUIERDO no depende de la variable
  // (es el UITI del circuito), el DERECHO si. El tamaño de los marcadores es un ARRAY --
  // todos en serieTam menos el del dia vigente, que va en serieTamActivo (el triple) --
  // asi que mover el slider de dia reescribe ese array en AMBAS series.
  function dibujarSeries(gd, diaIdx) {
    var cc = C(), cfg = cfgActual();
    var fechas = cc.dias.map(function (d) { return d.periodo; });
    var tam = fechas.map(function (_, i) {
      return i === diaIdx ? CTX.serieTamActivo : CTX.serieTam;
    });
    Plotly.restyle(gd, {
      x: [fechas, fechas],
      y: [cc.uitiTotalPorDia, cc.medianaPorDia[varActualCodigo()]],
      'marker.size': [tam, tam],
    }, [CTX.idx.serieUiti, CTX.idx.serieVar]);
    // El color de la serie derecha y el rotulo de su eje siguen a la variable activa.
    Plotly.restyle(gd, {'line.color': cfg.hue, 'marker.color': cfg.hue}, [CTX.idx.serieVar]);
    var relayout = {};
    relayout[CTX.ejes.serieDer + '.title.text'] = cfg.nombre + ' (' + cfg.unidad + ')';
    relayout[CTX.ejes.serieDer + '.color'] = cfg.hue;
    return Plotly.relayout(gd, relayout);
  }

  function aplicarDia() {
    var gd = d.getElementById(CTX.div);
    if (!gd || !gd._fullLayout) { return setTimeout(aplicarDia, 120); }
    var diaIdx = diaActual();
    dibujarMapa(gd, diaIdx);
    dibujarViolines(gd, diaIdx);
    dibujarSeries(gd, diaIdx);
    construirNube(gd, diaIdx);
    var dias = C().dias;
    d.getElementById('cl-aviso').textContent =
      CIRC + ' -- ' + dias.length + ' dias con eventos, del ' + dias[0].periodo +
      ' al ' + dias[dias.length - 1].periodo + '.';
  }

  // <select> de variable: cambia CUAL serie usa la nube (color + hover) para el dia
  // vigente -- el dia y la hora no se tocan. Sirve igual para las 4 climaticas y para
  // las 2 estaticas del vano.
  function cambiarVariable(gd, idx) {
    if (idx < 0 || idx >= CTX.variables.length || idx === VAR_ACTUAL) { return; }
    VAR_ACTUAL = idx;
    actualizarEtiquetas();
    dibujarSeries(gd, diaActual());
    construirNube(gd, diaActual());
  }

  // <select> de circuito: SWAP EN VIVO. Lee CTX.porCircuito[elegido] y reescribe
  // geometria/UITI/nube/violines de las MISMAS 14 trazas para ese circuito -- nunca
  // crea ni destruye trazas, nunca vuelve a ejecutar Python. Reemplaza por completo el
  // aviso de "un circuito a la vez" de la version anterior de este cuaderno.
  function cambiarCircuito(codigo) {
    if (!CTX.porCircuito[codigo] || codigo === CIRC) { return; }
    CIRC = codigo;
    RECENTRADO = false;
    if (VAR_ACTUAL >= CTX.variables.length) { VAR_ACTUAL = 0; }
    // El maximo del slider es propio de cada circuito: van de 1 a 79 dias con eventos.
    // Con un solo dia el maximo queda en 0 y `actualizarEtiquetas` lo deshabilita.
    var sliderDia = d.getElementById('cl-dia');
    if (sliderDia) { sliderDia.max = C().dias.length - 1; sliderDia.value = 0; }
    var gd = d.getElementById(CTX.div);
    Plotly.relayout(gd, {'title.text': 'Nube por vano -- ' + CIRC});
    actualizarEtiquetas();
    aplicarDia();
  }

  var sliderDia0 = d.getElementById('cl-dia');
  if (sliderDia0) { sliderDia0.addEventListener('input', aplicarDia); }

  var sliderHora = d.getElementById('cl-hora');
  if (sliderHora) {
    sliderHora.addEventListener('input', function () {
      var gd = d.getElementById(CTX.div);
      if (!gd || !gd._fullLayout) { return; }
      pintarNube(gd);
    });
  }

  var selVariable = d.getElementById('cl-variable');
  if (selVariable) {
    selVariable.addEventListener('change', function () {
      var gd = d.getElementById(CTX.div);
      if (!gd || !gd._fullLayout) { return; }
      var idx = CTX.variables.findIndex(function (v) { return v.codigo === selVariable.value; });
      if (idx >= 0) { cambiarVariable(gd, idx); }
    });
  }

  var selCircuito = d.getElementById('cl-circuito');
  if (selCircuito) {
    selCircuito.addEventListener('change', function () { cambiarCircuito(selCircuito.value); });
  }

  // El click solo aplica a la nube: se identifica por curveNumber === CTX.idx.nube, y
  // el vano/valor salen de los arrays cacheados por pointNumber. El valor mostrado es
  // SIEMPRE el de la hora y la variable activas al momento del click.
  function wireClick() {
    var gd = d.getElementById(CTX.div);
    if (!gd || !gd._fullLayout || typeof gd.on !== 'function') {
      return setTimeout(wireClick, 120);
    }
    gd.on('plotly_click', function (e) {
      var p = e.points && e.points[0];
      if (!p || p.curveNumber !== CTX.idx.nube) { return; }
      var fid = DIA_FIDS[p.pointNumber];
      var hora = horaActual();
      var serie = DIA_SERIES[p.pointNumber];
      var cfg = cfgActual();
      var valor = serie ? serie[Math.min(hora, serie.length - 1)] : null;
      d.getElementById('cl-info').innerHTML =
        '<b>Vano ' + fid + '</b> (' + CIRC + ') -- ' +
        (cfg.estatica ? 'atributo estatico del vano'
                      : (hora === 0 ? 'hora del evento' : hora + ' h antes')) +
        '<br>' + cfg.nombre + ': ' +
        (valor === null ? 's/d' : valor.toLocaleString() + ' ' + cfg.unidad);
    });
  }
  wireClick();

  actualizarEtiquetas();
  aplicarDia();
  // MapLibre inicializa de forma asincrona: un restyle/relayout disparado antes de que
  // el subplot de mapa este listo se pierde en silencio. Se repite el dibujado un par
  // de veces despues del arranque; es idempotente.
  [700, 2000].forEach(function (ms) {
    setTimeout(function () {
      var gd = d.getElementById(CTX.div);
      if (gd && gd._fullLayout) {
        dibujarMapa(gd, diaActual());
        encuadrarCircuito(gd);
      }
    }, ms);
  });

  // La figura es responsive: al cambiar el tamano de la ventana se redibuja y el mapa pasa
  // a tener otro tamano en pixeles. El encuadre se rehace con la medida nueva, o el
  // circuito se queda pequeno en una pantalla ancha. Con retardo, porque 'resize' se
  // dispara en cada cuadro del arrastre.
  var reencuadre = null;
  window.addEventListener('resize', function () {
    if (reencuadre) { clearTimeout(reencuadre); }
    reencuadre = setTimeout(function () {
      reencuadre = null;
      var gd = d.getElementById(CTX.div);
      if (gd && gd._fullLayout) { encuadrarCircuito(gd); }
    }, 200);
  });
})();
</script>
'''
    PANEL_JS = PANEL_JS_TEMPLATE.replace('__CTX_JSON__', json.dumps(CONTEXTO, separators=(',', ':')))

    # Chequeo de estilo: el TEMA del panel (bordes, sliders, acentos -- todo en PANEL_HTML)
    # sigue siendo rojo, nunca azul. La nube AHORA si puede ser azul, pero solo como color
    # semantico de la variable precipitacion (viaja en PANEL_JS, dato, no tema) -- por eso
    # el chequeo mira solo el chrome (PANEL_HTML), no los datos serializados en PANEL_JS.
    import re as _re
    _azul = _re.search(r'1e3a8a|eff6ff|bfdbfe|37, ?99, ?235', PANEL_HTML)
    assert _azul is None, f'token azul en el chrome del panel: {_azul.group(0)!r}'

    # include_plotlyjs=True embebe plotly.js en esta misma salida: el panel, la figura y su
    # libreria viajan juntos. `default_width='100%'` solo surte efecto porque la figura NO
    # lleva `width`, y `responsive` hace que se recalcule al cambiar el tamaño de la ventana.
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

    # El boton de encuadre, ENCIMA del mapa y a su izquierda, como en el simulador: alli cada
    # mapa lleva el suyo justo arriba, donde el mapa empieza. Estaba dentro del panel de
    # control, a media pantalla del mapa al que afecta.
    #
    # El texto es el del simulador sin su desambiguador: alli son "Centrar mapa base" y
    # "Centrar mapa simulado" porque hay DOS mapas, y aqui hay uno solo. La descripcion de lo
    # que hace -- encuadrar sobre los vanos con eventos, que no es lo mismo que el encuadre
    # automatico sobre el circuito entero -- se queda en la etiqueta del mouse, que es donde
    # estaba.
    #
    # El `id` no cambia: es de donde cuelga su manejador en PANEL_JS.
    BARRA_ENCUADRE = """
<div class="barra-encuadre">
  <button type="button" id="cl-centrar"
    title="Encuadra el mapa sobre los vanos que registraron eventos en el periodo elegido. El encuadre automatico usa el circuito completo, que en un circuito largo deja los vanos con eventos apretados en una esquina.">Centrar mapa</button>
</div>
"""

    # El panel y la figura dejan de apilarse: van en una fila de dos columnas. El JS queda
    # FUERA de la fila -- no pinta nada, solo cuelga los manejadores -- y sigue encontrando
    # sus elementos por id, que no cambian al envolverlos.
    PANEL_COMPLETO = CSS_DOS_COLUMNAS + (
        # 25/75 y no el 30/70 por defecto: el panel del clima perdio dos bloques de texto y
        # dos puntos de fuente, asi que le sobra ancho, y el mapa y los violines lo agradecen.
        '<div class="cuerpo-2col" style="--ancho-controles: 25%">'
        f'<div class="col-controles">{PANEL_HTML}</div>'
        f'<div class="col-figuras">{BARRA_ENCUADRE}{FIGURA_HTML}</div>'
        '</div>'
    ) + PANEL_JS


    # El MISMO html, envuelto en un documento minimo, escrito a disco y abierto en el
    # navegador: ahi el panel usa todo el ancho de la pantalla en vez del de la celda. No se
    # vuelve a serializar nada -- se reusa PANEL_COMPLETO, que ya trae plotly.js embebido, asi
    # que el archivo funciona sin conexion y sin el cuaderno.
    def exportar_y_abrir(html_panel, *, abrir=True):
        import webbrowser

        destino = (Path(ruta_html) if ruta_html is not None
                   else REPO_ROOT / 'reports' / 'paneles' / '01_uiti_vano_clima.html')
        destino.parent.mkdir(parents=True, exist_ok=True)
        documento = (
            '<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>Nube por vano -- {CIRCUITO}</title>\n'
            # margin 0 + un div al 100%: sin esto el navegador deja el margen por defecto del
            # body y la figura no llega a los bordes de la pantalla.
            '<style>html,body{margin:0;padding:12px;box-sizing:border-box;'
            'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;}'
            f'#{DIV_FIGURA}{{width:100%;}}</style>\n</head>\n<body>\n'
            + html_panel + '\n</body>\n</html>\n'
        )
        destino.write_text(documento, encoding='utf-8')
        mb = destino.stat().st_size / 1024 ** 2
        print(f'panel autocontenido escrito en {_corta(destino, REPO_ROOT)} ({mb:,.1f} MB)')
        if abrir:
            webbrowser.open(destino.resolve().as_uri())
            print('abriendo en el navegador por defecto -- '
                  f'pesa {mb:,.0f} MB, asi que la primera carga puede tardar unos segundos')
        else:
            print('ABRIR_EN_NAVEGADOR = False: no se abre nada, el archivo queda escrito')
        return destino


    RUTA_PANEL = exportar_y_abrir(PANEL_COMPLETO, abrir=ABRIR_EN_NAVEGADOR)

    return RUTA_PANEL
