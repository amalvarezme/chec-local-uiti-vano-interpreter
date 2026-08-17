"""El tablero de agrupamiento: circuitos y vanos por UITI acumulado y eventos.

## De donde sale este modulo

Es el cuaderno `02_uiti_vano_kmeans.ipynb`, movido aqui. Ver
`chec_tableros.clima` para el porque del traslado y para el criterio de reparto
entre constantes de modulo y tuberia dentro de `construir()`.

## Lo propio de este tablero

El cuaderno arma DOS tableros -- circuitos arriba, vanos abajo -- y exporta **solo
el de vanos**: es el que responde la pregunta operativa. El de circuitos queda
como paso intermedio, y por eso su figura se construye pero no se escribe.

Ese detalle es la razon de que aqui el HTML embeba plotly.js (`include_plotlyjs=True`)
y anteponga `PANEL_CSS`: los dos viajaban con el tablero de circuitos, que no se
exporta.

## Lo unico que cambia respecto del cuaderno

- Los `display(HTML(...))` desaparecen: no hay kernel ni celda donde pintar.
- `REPO_ROOT`, el destino del HTML y el abrir-en-navegador los pasa quien llama.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.csv as pacsv
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
from scipy.stats import gaussian_kde
from sklearn.cluster import KMeans
from sklearn.preprocessing import MinMaxScaler, StandardScaler

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
GRID_KDE = 64
SEMILLA = 42


# Sube desde el cwd hasta encontrar data/Indicadores_vano_v3.csv, para que el cuaderno
# funcione sin importar desde que directorio se ejecute (Jupyter local o Colab/Kaggle).
def find_repo_root():
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        if (candidate / 'data/Indicadores_vano_v3.csv').exists():
            return candidate
    raise FileNotFoundError('No se encontro data/Indicadores_vano_v3.csv subiendo desde el cwd')

# Ninguno de los dos tableros deja elegir ya la escala de los ejes ni el preproceso. El
# eje Y va en logaritmica -- el UITI acumulado abarca varios ordenes de magnitud, y en
# lineal los grupos bajos se apilan contra el cero --, el eje X lineal y el escalador
# minmax. Antes se precomputaban las ocho combinaciones para que los selectores saltaran
# entre ellas sin recalcular; con una sola, K-Means se ajusta UNA vez por tablero en vez de
# ocho, y las combinaciones embebidas bajan de 168 a 21. La lista se conserva con un
# elemento porque todo lo que viene abajo indexa por espacio y el JS busca su geometria por
# esa clave.
LOG_X, LOG_Y, PREPROCESO = False, True, 'minmax'
ESPACIOS = [(LOG_X, LOG_Y, PREPROCESO)]
IDX_ESPACIO_DEFECTO = 0



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
    """Construye el tablero de vanos y devuelve la ruta del HTML autocontenido."""
    ABRIR_EN_NAVEGADOR = bool(abrir)

    REPO_ROOT = Path(raiz) if raiz is not None else find_repo_root()

    # Solo 3 columnas: el CSV completo trae ~270 columnas climaticas por evento.
    # ABRIR_EN_NAVEGADOR: ademas de pintar los dos tableros dentro del cuaderno, escribe el
    # MISMO HTML autocontenido en reports/paneles/ y lo abre en el navegador por defecto. Ahi
    # los tableros usan todo el ancho de la pantalla, no el de la celda de Jupyter. Ponerlo en
    # False para no abrir nada (Databricks, Colab o nbconvert, donde no hay navegador local).

    # El CSV se lee DOS veces en este cuaderno -- aqui por circuito y mas abajo por vano --,
    # de modo que el lector se define una vez y se reusa.
    def leer_eventos(columnas):
        """Lee el CSV de eventos por bloques y devuelve solo `columnas`, en ese orden.

    Se usa el lector incremental de pyarrow y no `pd.read_csv`. El resultado es el mismo
    valor por valor, pero `pd.read_csv(engine='pyarrow')` materializa el archivo de 566 MB
    antes de descartar las ~267 columnas que no se usan, y aqui eso pasa dos veces. FECHA
    llega como fecha y no como texto; el to_datetime de abajo la deja igual.
    """
        lector = pacsv.open_csv(
            str(REPO_ROOT / 'data' / 'Indicadores_vano_v3.csv'),
            convert_options=pacsv.ConvertOptions(include_columns=list(columnas)),
        )
        # El reindexado explicito se conserva para que el orden no dependa del lector.
        return lector.read_all().to_pandas()[list(columnas)]


    _COLS = ['CIRCUITO', 'UITI_VANO', 'FECHA']
    df = leer_eventos(_COLS)
    df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
    df['UITI_VANO'] = pd.to_numeric(df['UITI_VANO'], errors='coerce').fillna(0.0)
    df['MES'] = df['FECHA'].dt.to_period('M')

    MESES = sorted(df['MES'].unique())
    # Todos los pares (desde, hasta) con desde <= hasta: el calendario ajusta a uno de estos.
    RANGOS = [(i, j) for i in range(len(MESES)) for j in range(i, len(MESES))]
    IDX_RANGO_COMPLETO = RANGOS.index((0, len(MESES) - 1))

    print(f'{len(df):,} eventos | {df["CIRCUITO"].nunique()} circuitos | '
          f'{df["FECHA"].min():%Y-%m-%d} a {df["FECHA"].max():%Y-%m-%d}')
    print(f'{len(RANGOS)} rangos x 1 espacio fijo (eje x lineal, eje y logaritmico, minmax) '
          f'= {len(RANGOS)} combinaciones')


    def tabla_circuitos(desde, hasta):
        """UITI acumulado y numero de eventos por circuito, restringido a los meses [desde, hasta]."""
        sub = df[(df['MES'] >= MESES[desde]) & (df['MES'] <= MESES[hasta])]
        return (
            sub.groupby('CIRCUITO')
            # Un evento es una FECHA distinta, no una fila: una misma salida golpea muchos
            # vanos y genera muchas filas. Es la definicion que usa el agrupamiento de
            # circuitos del reporte (`count_unique_event_dates`, en
            # `compute_circuit_criticality_groups`); contar filas daba una mediana de 468
            # eventos por circuito contra los 18 reales, hasta 111 veces mas.
            .agg(uiti_acumulado=('UITI_VANO', 'sum'), num_eventos=('FECHA', 'nunique'))
            .reset_index()
        )


    def aplicar_log(X, logs):
        """log10 columna por columna, segun que ejes lo tengan activado."""
        # Seguro en esta base: el minimo por circuito es 2 eventos y 0.25 de UITI, nunca 0.
        V = np.array(X, dtype=float, copy=True)
        for c, activo in enumerate(logs):
            if activo:
                V[:, c] = np.log10(V[:, c])
        return V


    def agrupar(tabla, logs, prep):
        """K-Means a 4 grupos sobre el espacio ajustado.

    Devuelve la tabla etiquetada y la geometria de la particion (centroides y parametros
    del escalador), que es lo que necesitan los contornos de membresia.
    """
        X = aplicar_log(tabla[['num_eventos', 'uiti_acumulado']].to_numpy(dtype=float), logs)

        escalador = PREPROCESOS[prep]().fit(X)
        modelo = KMeans(n_clusters=4, random_state=SEMILLA, n_init=10).fit(escalador.transform(X))
        tabla = tabla.assign(_cluster=modelo.labels_)

        # El id que devuelve K-Means es arbitrario: el nombre del grupo se asigna por el
        # ranking de la MEDIANA del UITI acumulado, de menor a mayor.
        orden = tabla.groupby('_cluster')['uiti_acumulado'].median().sort_values().index.tolist()
        tabla['grupo'] = tabla['_cluster'].map({c: i for i, c in enumerate(orden)})

        # Todo escalador se reduce a (v - offset) / scale, asi el JS aplica uno solo.
        if prep == 'minmax':
            offset, scale = escalador.data_min_, escalador.data_range_
        else:
            offset, scale = escalador.mean_, escalador.scale_

        geometria = {
            'logs': [bool(logs[0]), bool(logs[1])],
            'offset': np.round(offset, 6).tolist(),
            'scale': np.round(scale, 6).tolist(),
            # Centroides reordenados al mismo indice de grupo que las etiquetas.
            'centroides': np.round(modelo.cluster_centers_[orden], 6).tolist(),
        }
        return tabla.drop(columns='_cluster'), geometria


    def membresia(X_display, geometria):
        """Grupo de cada punto por centroide mas cercano; replica en numpy lo que hace el JS."""
        Z = ((aplicar_log(X_display, geometria['logs']) - np.array(geometria['offset']))
             / np.array(geometria['scale']))
        d = ((Z[:, None, :] - np.array(geometria['centroides'])[None, :, :]) ** 2).sum(axis=2)
        return d.argmin(axis=1)


    def curva_kde(valores, log):
        """Densidad de una variable en el espacio en que corrio K-Means, devuelta en unidades originales."""
        valores = np.asarray(valores, dtype=float)
        if valores.size < 3 or np.allclose(valores, valores[0]):
            return [], []
        base = np.log10(valores) if log else valores
        grid = np.linspace(base.min(), base.max(), GRID_KDE)
        densidad = gaussian_kde(base)(grid)
        # Se redondea antes de serializar: el cuaderno embebe las 168 combinaciones y los
        # decimales de mas solo inflan su tamano.
        return (np.round(10.0 ** grid if log else grid, 4).tolist(),
                np.round(densidad, 6).tolist())

    # El JavaScript del panel no ajusta ningun modelo: solo intercambia datos ya agrupados y
    # evalua "centroide mas cercano" sobre una grilla para dibujar los contornos. Cada
    # combinacion se resuelve aqui, con scikit-learn, y viaja embebida en la salida.
    # K-Means se ajusta UNA sola vez por espacio, sobre la ventana temporal completa. Los
    # centroides y el escalador quedan fijos: cambiar el rango de fechas ya no redefine los
    # grupos, solo mueve los circuitos dentro de una particion que no se mueve. Antes cada
    # rango reajustaba las fronteras, y "Alto" no significaba lo mismo de un rango a otro.
    TABLA_COMPLETA = tabla_circuitos(0, len(MESES) - 1)
    GEOMETRIA_FIJA = {}
    for e, (log_x, log_y, prep) in enumerate(ESPACIOS):
        _agrupada_full, _geo = agrupar(TABLA_COMPLETA, (log_x, log_y), prep)
        # La regla de centroide mas cercano tiene que reproducir las etiquetas del ajuste,
        # porque es la unica que se usa despues para cualquier otro rango.
        assert np.array_equal(
            membresia(TABLA_COMPLETA[['num_eventos', 'uiti_acumulado']].to_numpy(float), _geo),
            _agrupada_full['grupo'].to_numpy(),
        ), f'la regla de centroide mas cercano no reproduce el ajuste del espacio {e}'
        GEOMETRIA_FIJA[e] = _geo

    # Extension FIJA, tomada de la ventana completa: es la misma sobre la que se ajustaron los
    # centroides. Con ella los ejes y la grilla del contorno no se mueven al cambiar el rango,
    # asi dos rangos distintos se pueden comparar mirando donde caen los puntos.
    EXTENSION_FIJA = [
        float(TABLA_COMPLETA['num_eventos'].min()), float(TABLA_COMPLETA['num_eventos'].max()),
        float(round(TABLA_COMPLETA['uiti_acumulado'].min(), 4)),
        float(round(TABLA_COMPLETA['uiti_acumulado'].max(), 4)),
    ]

    COMBINACIONES = {}
    for r, (desde, hasta) in enumerate(RANGOS):
        tabla = tabla_circuitos(desde, hasta)
        for e, (log_x, log_y, prep) in enumerate(ESPACIOS):
            geometria = GEOMETRIA_FIJA[e]
            # Membresia del rango elegido contra los centroides fijos: no se reajusta nada.
            agrupada = tabla.assign(grupo=membresia(
                tabla[['num_eventos', 'uiti_acumulado']].to_numpy(float), geometria))

            bloque = []
            for g in range(4):
                sel = agrupada[agrupada['grupo'] == g]
                kde_x, dens_x = curva_kde(sel['num_eventos'], log_x)
                kde_y, dens_y = curva_kde(sel['uiti_acumulado'], log_y)
                bloque.append({
                    'x': sel['num_eventos'].astype(int).tolist(),
                    'y': np.round(sel['uiti_acumulado'], 2).tolist(),
                    'circuitos': sel['CIRCUITO'].tolist(),
                    'kde_x': kde_x, 'dens_x': dens_x,
                    'kde_y': kde_y, 'dens_y': dens_y,
                })

            COMBINACIONES[f'{r}|{e}'] = {
                'grupos': bloque,
                'geometria': geometria,
            }

    # El nombre del grupo solo significa algo si el ranking por mediana es estrictamente creciente.
    # Con centroides fijos el orden por mediana esta garantizado solo en la ventana completa:
    # en un rango corto un grupo puede quedar con pocos circuitos y cruzarse con el vecino.
    # Se cuenta y se informa en vez de asumirlo.
    # Un grupo VACIO y un orden ROTO son dos cosas distintas y antes se contaban juntas:
    # np.median([]) emite un RuntimeWarning ("Mean of empty slice"), devuelve nan, y como
    # `nan < x` es False el rango caia en la misma bolsa que un cruce real. Sobre esta base
    # eran 51 de 168 "rotos", pero solo 8 lo estaban de verdad: los otros 43 tenian algun
    # grupo sin circuitos, donde no hay nada que ordenar. Con otra base la mezcla cambia,
    # asi que se informan por separado en vez de sumarlos.
    _medianas = {
        clave: [float(np.median(g['y'])) if g['y'] else None for g in combo['grupos']]
        for clave, combo in COMBINACIONES.items()
    }
    vacias = [c for c, m in _medianas.items() if any(v is None for v in m)]
    rotas = [c for c, m in _medianas.items()
             if all(v is not None for v in m) and not all(m[g] < m[g + 1] for g in range(3))]
    print(f'{len(COMBINACIONES)} combinaciones | K-Means ajustado una vez '
          '(espacio fijo, sobre la ventana completa)')
    print(f'rangos con algun grupo VACIO (nada que ordenar): {len(vacias)} de {len(COMBINACIONES)}')
    print(f'rangos donde el orden por mediana NO se sostiene: {len(rotas)} de {len(COMBINACIONES)}')

    # La figura tiene 22 trazas fijas y siempre son esas 22: 1 contorno de membresia,
    # 4 scatter, 4 KDE del eje x, 4 KDE del eje y, 1 barra de conteos y 8 violines (4 del UITI
    # acumulado + 4 del numero de eventos). El panel no crea ni destruye trazas, solo les
    # reescribe los datos; los violines reusan los mismos arrays por grupo que el scatter, asi
    # que no agregan nada al payload.
    fig = make_subplots(
        rows=5, cols=2,
        row_heights=[0.13, 0.40, 0.15, 0.16, 0.16], column_widths=[0.78, 0.22],
        horizontal_spacing=0.02, vertical_spacing=0.07,
    )

    inicial = COMBINACIONES[f'{IDX_RANGO_COMPLETO}|{IDX_ESPACIO_DEFECTO}']
    grupos_ini = inicial['grupos']

    # Escala discreta de 4 escalones: cada banda del contorno toma el color de su grupo.
    ESCALA_CONTORNO = []
    for g, color in enumerate(COLORES_GRUPOS):
        ESCALA_CONTORNO.append([g / 4.0, color])
        ESCALA_CONTORNO.append([(g + 1) / 4.0, color])

    fig.add_trace(go.Contour(                                       # traza 0: membresia
        z=[[0, 0], [0, 0]], x=[0, 1], y=[0, 1],
        colorscale=ESCALA_CONTORNO, zmin=-0.5, zmax=3.5, showscale=False,
        opacity=0.28, hoverinfo='skip', line=dict(width=1.2, color='rgba(120,20,20,0.6)'),
        contours=dict(start=-0.5, end=3.5, size=1, coloring='fill'),
        name='Membresia', showlegend=False,
    ), row=2, col=1)
    for g in range(4):                                              # trazas 1-4: scatter
        fig.add_trace(go.Scattergl(
            x=grupos_ini[g]['x'], y=grupos_ini[g]['y'], mode='markers', name=NOMBRES_GRUPOS[g],
            legendgroup=NOMBRES_GRUPOS[g],
            marker=dict(size=9, color=COLORES_GRUPOS[g],
                        line=dict(width=0.5, color='rgba(60,60,60,0.6)')),
            customdata=grupos_ini[g]['circuitos'],
            # El grupo va fijo en la plantilla, no en customdata: la traza g siempre es el
            # grupo g, lo unico que cambia con los filtros es que circuitos caen adentro.
            hovertemplate=(f'<b>%{{customdata}}</b><br>Grupo: <b>{NOMBRES_GRUPOS[g]}</b>'
                           '<br>Eventos: %{x:,}<br>UITI acumulado: %{y:,.1f}<extra></extra>'),
        ), row=2, col=1)
    for g in range(4):                                              # trazas 5-8: KDE eje x
        fig.add_trace(go.Scatter(
            x=grupos_ini[g]['kde_x'], y=grupos_ini[g]['dens_x'], mode='lines', fill='tozeroy',
            name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g], showlegend=False,
            line=dict(width=1.2, color=COLORES_GRUPOS[g]),
            fillcolor=COLORES_GRUPOS[g].replace('rgb', 'rgba').replace(')', ',0.25)'),
            hoverinfo='skip',
        ), row=1, col=1)
    for g in range(4):                                              # trazas 9-12: KDE eje y
        fig.add_trace(go.Scatter(
            x=grupos_ini[g]['dens_y'], y=grupos_ini[g]['kde_y'], mode='lines', fill='tozerox',
            name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g], showlegend=False,
            line=dict(width=1.2, color=COLORES_GRUPOS[g]),
            fillcolor=COLORES_GRUPOS[g].replace('rgb', 'rgba').replace(')', ',0.25)'),
            hoverinfo='skip',
        ), row=2, col=2)
    conteos_ini = [len(grupos_ini[g]['x']) for g in range(4)]
    fig.add_trace(go.Bar(                                           # traza 13: conteo por grupo
        x=NOMBRES_GRUPOS, y=conteos_ini, text=conteos_ini, textposition='outside',
        marker=dict(color=COLORES_GRUPOS, line=dict(width=0.5, color='rgba(60,60,60,0.6)')),
        showlegend=False, hovertemplate='%{x}: %{y} circuitos<extra></extra>', cliponaxis=False,
    ), row=3, col=1)
    # Trazas 14-17 y 18-21: distribucion completa por grupo de cada variable. `box_visible`
    # deja la mediana a la vista, que es exactamente el criterio con que se nombran los grupos.
    for fila, (clave, etiqueta) in enumerate([('y', 'UITI acumulado'), ('x', 'Número de eventos')]):
        for g in range(4):
            fig.add_trace(go.Violin(
                x=[NOMBRES_GRUPOS[g]] * len(grupos_ini[g][clave]), y=grupos_ini[g][clave],
                name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g], showlegend=False,
                line=dict(color='rgba(90,15,20,0.85)', width=1),
                fillcolor=COLORES_GRUPOS[g], opacity=0.85,
                box_visible=True, meanline_visible=False, points=False, spanmode='hard',
                hovertemplate=f'%{{x}} -- {etiqueta}: %{{y:,.1f}}<extra></extra>',
            ), row=4 + fila, col=1)

    # Traza 22: el porcentaje va DENTRO de la barra. Una traza de barras tiene un solo
    # `text`/`textposition`, asi que el conteo de afuera y el porcentaje de adentro no pueden
    # salir de la misma; este texto se posiciona a media altura de cada barra.
    fig.add_trace(go.Scatter(
        x=NOMBRES_GRUPOS, y=[c / 2 for c in conteos_ini], mode='text',
        text=[f'{100 * c / max(sum(conteos_ini), 1):.1f}%' for c in conteos_ini],
        # Color por punto: sobre las dos barras oscuras un texto oscuro no se lee. Los grupos
        # estan ordenados de claro a oscuro, asi que el corte es fijo.
        textposition='middle center',
        textfont=dict(size=11, color=['rgb(40,10,12)', 'rgb(40,10,12)', 'white', 'white']),
        showlegend=False, hoverinfo='skip',
    ), row=3, col=1)

    fig.update_layout(
        title=dict(
            text='Agrupamiento de circuitos por UITI acumulado y número de eventos'
                 '<br><sup>K-Means (k=4); los grupos se nombran por el ranking de la mediana '
                 'del UITI acumulado</sup>',
            x=0.5, xanchor='center', yref='container', y=0.96, yanchor='top',
        ),
        legend=dict(title_text='', orientation='h', x=0.5, xanchor='center', y=1.02, yanchor='bottom'),
        # Mismo ajuste que el tablero de vanos: con 110 la leyenda pisaba el subtitulo.
        margin=dict(t=165, r=30, b=60, l=90),
        # SIN `width`: el ancho lo decide el contenedor. Con un ancho fijo en px la figura
        # no aprovecha la pantalla al abrirse en el navegador ni se reajusta al redimensionar.
        # El alto SI queda fijo -- son 5 filas apiladas y un alto elastico las aplasta.
        height=1260, template='plotly_white', bargap=0.45,
    )
    # El KDE superior comparte el eje x del scatter y el KDE derecho su eje y; el de barras es
    # categorico y queda independiente a proposito.
    fig.update_xaxes(matches='x3', row=1, col=1)
    fig.update_yaxes(matches='y3', row=2, col=2)
    fig.update_xaxes(title_text='Número de eventos', row=2, col=1)
    fig.update_yaxes(title_text='UITI acumulado', row=2, col=1)
    # La densidad se lee por forma, no por valor: sus ticks solo agregan ruido (y sobre el eje del
    # UITI salen en notacion micro, porque la densidad esta en unidades de 1/UITI).
    fig.update_yaxes(title_text='Densidad', showticklabels=False, row=1, col=1)
    fig.update_xaxes(title_text='Densidad', showticklabels=False, row=2, col=2)
    fig.update_yaxes(title_text='Circuitos', rangemode='tozero', row=3, col=1)
    fig.update_xaxes(visible=False, row=1, col=2)
    fig.update_yaxes(visible=False, row=1, col=2)
    fig.update_yaxes(title_text='UITI acumulado', row=4, col=1)
    fig.update_yaxes(title_text='Número de eventos', row=5, col=1)
    for fila_vacia in (3, 4, 5):
        fig.update_xaxes(visible=False, row=fila_vacia, col=2)
        fig.update_yaxes(visible=False, row=fila_vacia, col=2)

    # Este tablero no tiene titulos de subplot, asi que el conteo de muestras va en el TITULO
    # DEL EJE de las barras y de los dos violines. La clave del eje se resuelve desde la traza:
    # escribirla a mano se rompe en silencio si alguien agrega un subplot antes.
    def _clave_eje(traza, cual):
        return f'{cual}axis' + (getattr(traza, cual + 'axis', None) or cual)[1:]


    EJES_N = {'barras': _clave_eje(fig.data[13], 'y'),
              'violinU': _clave_eje(fig.data[14], 'y'),
              'violinN': _clave_eje(fig.data[18], 'y')}
    TITULOS_N = {'barras': 'Circuitos', 'violinU': 'UITI acumulado',
                 'violinN': 'Número de eventos'}
    assert fig.data[13].type == 'bar' and fig.data[14].type == fig.data[18].type == 'violin'

    # El print cierra la celda a proposito: si terminara en un update_*(), Jupyter mostraria
    # la Figure devuelta y quedarian dos figuras, una de ellas sin panel de control.
    print(f'{len(fig.data)} trazas: 1 contorno + 4 scatter + 8 KDE + 1 barras + 8 violines')

    DIV_FIGURA = 'agrupamiento-circuitos'
    PRIMER_DIA = f'{MESES[0]}-01'
    ULTIMO_DIA = str(df['FECHA'].max().date())
    RESOLUCION_CONTORNO = 90

    # Todo lo que el JS necesita, resuelto en Python: no ajusta modelos ni recalcula agregados.
    CONTEXTO = {
        'div': DIV_FIGURA,
        'meses': [str(m) for m in MESES],
        # Ultimo dia real de cada mes: el CSV declara el periodo cerrado, no el mes suelto.
        'finMes': [str(m.to_timestamp(how='end').date()) for m in MESES],
        'rangos': RANGOS,
        'espacios': [[bool(lx), bool(ly), prep] for lx, ly, prep in ESPACIOS],
        'grupos': NOMBRES_GRUPOS,
        'resolucion': RESOLUCION_CONTORNO,
        'ejesN': EJES_N,
        'titulosN': TITULOS_N,
        'combinaciones': COMBINACIONES,
        'extension': EXTENSION_FIJA,
    }

    PANEL_CSS = '''
<style>
  .panel-agrup {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 13px;
    display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-end;
    max-width: 100%; margin: 0 0 6px 0; padding: 12px 14px;
    border: 1px solid #cfe3ac; border-left: 4px solid rgb(0,128,36);
    border-radius: 6px; background: #f3f8ec; color: #2b2b2b;
  }
  .panel-agrup label { display: block; font-weight: 600; margin-bottom: 4px; }
  .panel-agrup input[type="date"], .panel-agrup select {
    font: inherit; padding: 4px 6px; border: 1px solid #a8c97a;
    border-radius: 4px; background: #fff; color: #2b2b2b;
  }
  .panel-agrup .chk { font-weight: 600; display: flex; align-items: center; gap: 6px; }
  .panel-agrup .chk input { margin: 0; }
  .panel-agrup .grupo-chk { display: flex; flex-direction: column; gap: 6px; }
  .panel-agrup button {
    font: inherit; font-weight: 600; padding: 6px 12px; cursor: pointer;
    border: 1px solid rgb(0,128,36); border-radius: 4px;
    background: rgb(0,128,36); color: #fff;
  }
  .panel-agrup button:hover { background: rgb(0,102,29); }
  .panel-aviso {
    flex-basis: 100%; font-size: 12px; color: #747378; margin: 0; font-weight: 400;
  }
</style>
'''
    # El CSS vive aparte porque el tablero de VANOS reusa la clase `.panel-agrup` pero no
    # lleva su propio <style>: exportarlo solo (ver la celda de export y el comando de
    # Databricks) requiere anteponerle este bloque, o sale sin estilos.
    PANEL_HTML = PANEL_CSS + f'''
<div class="panel-agrup">
  <div><label for="ag-desde">Desde</label>
       <input type="date" id="ag-desde" min="{PRIMER_DIA}" max="{ULTIMO_DIA}" value="{PRIMER_DIA}"></div>
  <div><label for="ag-hasta">Hasta</label>
       <input type="date" id="ag-hasta" min="{PRIMER_DIA}" max="{ULTIMO_DIA}" value="{ULTIMO_DIA}"></div>
  <div><button type="button" id="ag-csv">Descargar etiquetas (CSV)</button></div>
  <p class="panel-aviso" id="ag-aviso"></p>
</div>
'''

    PANEL_JS = '''
<script type="text/javascript">
(function () {
  var CTX = %s;
  var d = document;

  function idxMes(valor) {
    // El calendario ajusta a mes completo: se toma el mes de la fecha elegida y se
    // acota al rango disponible en la base.
    var i = CTX.meses.indexOf((valor || '').slice(0, 7));
    return i < 0 ? null : i;
  }

  function idxRango(desde, hasta) {
    for (var i = 0; i < CTX.rangos.length; i++) {
      if (CTX.rangos[i][0] === desde && CTX.rangos[i][1] === hasta) return i;
    }
    return null;
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

  function contorno(combo) {
    // Membresia por centroide mas cercano en el espacio ajustado: la misma regla que
    // scikit-learn usa en predict(), verificada contra sus etiquetas del lado de Python.
    var geo = combo.geometria, ext = CTX.extension, n = CTX.resolucion;
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

  var ESTADO = null;   // configuracion vigente, para que el boton exporte lo que se ve

  function csvActual() {
    // Mismo esquema y mismo orden que tabla_etiquetas() en Python: si los dos caminos
    // no coincidieran, el CSV del boton y el del kernel contarian historias distintas.
    var s = ESTADO, filas = [];
    for (var g = 0; g < 4; g++) {
      var b = s.bloque[g];
      for (var i = 0; i < b.circuitos.length; i++) {
        filas.push({c: b.circuitos[i], e: CTX.grupos[g], n: b.x[i], u: b.y[i]});
      }
    }
    filas.sort(function (p, q) { return q.u - p.u; });   // UITI acumulado descendente

    var desde = CTX.meses[s.a] + '-01';
    var hasta = CTX.finMes[s.b];
    var cab = ['desde', 'hasta', 'circuito', 'etiqueta', 'num_eventos', 'uiti_acumulado'];
    var out = [cab.join(',')];
    filas.forEach(function (f) {
      out.push([desde, hasta, '"' + f.c + '"', f.e, f.n, f.u].join(','));
    });
    return {texto: out.join('\\n') + '\\n',
            nombre: 'etiquetas_circuitos_' + CTX.meses[s.a] + '_' + CTX.meses[s.b] +
                    '_x' + (s.logx ? 'log' : 'lin') + '_y' + (s.logy ? 'log' : 'lin') +
                    '_' + s.prep + '.csv'};
  }

  function descargar() {
    if (!ESTADO) { return; }
    var csv = csvActual();
    var url = URL.createObjectURL(new Blob([csv.texto], {type: 'text/csv;charset=utf-8;'}));
    var a = d.createElement('a');
    a.href = url; a.download = csv.nombre;
    d.body.appendChild(a); a.click(); d.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function aplicar() {
    var gd = d.getElementById(CTX.div);
    if (!gd || !gd._fullLayout) { return setTimeout(aplicar, 120); }

    var a = idxMes(d.getElementById('ag-desde').value);
    var b = idxMes(d.getElementById('ag-hasta').value);
    if (a === null) a = 0;
    if (b === null) b = CTX.meses.length - 1;
    if (a > b) { var t = a; a = b; b = t; }   // fechas invertidas: se ordenan solas

    // El espacio es fijo -- eje x lineal, eje y logaritmico, minmax -- y ya no hay
    // controles que lo cambien: `CTX.espacios` trae uno solo. Se lee de ahi y no de
    // constantes escritas aqui, para que el dibujo y el nombre del CSV no puedan
    // contradecir a la geometria con que se ajusto K-Means del lado de Python.
    var e = 0, esp = CTX.espacios[0];
    var logx = esp[0], logy = esp[1], prep = esp[2];

    var combo = CTX.combinaciones[idxRango(a, b) + '|' + e];
    if (!combo) { return; }
    var bloque = combo.grupos;
    ESTADO = {a: a, b: b, logx: logx, logy: logy, prep: prep, bloque: bloque};

    var sx = [], sy = [], scd = [], kx = [], ky = [], conteos = [];
    for (var g = 0; g < 4; g++) {
      sx.push(bloque[g].x); sy.push(bloque[g].y); scd.push(bloque[g].circuitos);
      conteos.push(bloque[g].x.length);
    }
    for (var g = 0; g < 4; g++) { kx.push(bloque[g].kde_x); ky.push(bloque[g].dens_x); }
    for (var g = 0; g < 4; g++) { kx.push(bloque[g].dens_y); ky.push(bloque[g].kde_y); }

    var ct = contorno(combo);
    Plotly.restyle(gd, {z: [ct.z], x: [ct.x], y: [ct.y]}, [0]);
    Plotly.restyle(gd, {x: sx, y: sy, customdata: scd}, [1, 2, 3, 4]);
    Plotly.restyle(gd, {x: kx, y: ky}, [5, 6, 7, 8, 9, 10, 11, 12]);
        // El porcentaje va DENTRO de la barra solo si la barra es lo bastante alta. En una
    // barra muy baja el texto de media altura cae sobre el eje y se encima con el nombre
    // del grupo; en ese caso se pega al conteo de afuera, que es donde si hay sitio.
    var totalC = conteos[0] + conteos[1] + conteos[2] + conteos[3];
    var maxC = Math.max.apply(null, conteos) || 1;
    var pctTxt = conteos.map(function (c) {
      // Simbolo duplicado: el bloque se arma con formateo de cadena.
      return totalC ? (100 * c / totalC).toFixed(1) + '%%' : '';
    });
    var bajo = conteos.map(function (c) { return c / maxC < 0.12; });
    Plotly.restyle(gd, {y: [conteos], text: [conteos.map(
      function (c, i) { return bajo[i] ? c + '  ' + pctTxt[i] : String(c); })]},
      [13]);
    Plotly.restyle(gd, {
      y: [conteos.map(function (c) { return c / 2; })],
      text: [pctTxt.map(function (p, i) { return bajo[i] ? '' : p; })],
    }, [22]);
    // El porcentaje se recalcula sobre el total de circuitos de la combinacion vigente,
    // no sobre los 208: si el rango deja circuitos sin eventos, el reparto es sobre los
    // que efectivamente entraron.
    // Los violines reciben los mismos arrays del scatter: el UITI acumulado va contra el
    // eje y del grupo y el numero de eventos contra su eje x.
    var vx = [], vy = [];
    for (var g = 0; g < 4; g++) {
      vx.push(bloque[g].y.map(function () { return CTX.grupos[g]; })); vy.push(bloque[g].y);
    }
    Plotly.restyle(gd, {x: vx, y: vy}, [14, 15, 16, 17]);
    vx = []; vy = [];
    for (var g = 0; g < 4; g++) {
      vx.push(bloque[g].x.map(function () { return CTX.grupos[g]; })); vy.push(bloque[g].x);
    }
    Plotly.restyle(gd, {x: vx, y: vy}, [18, 19, 20, 21]);
    // xaxis/xaxis3 son el eje x del KDE superior y del scatter; yaxis3/yaxis4 el eje y del
    // scatter y del KDE derecho. Cada eje toma su propio log. El de barras no se toca.
    var tx = logx ? 'log' : 'linear', ty = logy ? 'log' : 'linear';
    // Limites FIJOS, de la ventana completa. Sin esto cada rango reencuadra los ejes y un
    // circuito parece moverse cuando lo unico que cambio fue la escala. En log Plotly
    // espera el rango YA en log10.
    var ex = CTX.extension;
    function lim(lo, hi, log) {
      return log ? [Math.log10(lo * 0.85), Math.log10(hi * 1.15)]
                 : [0, hi * 1.05];
    }
    var rx = lim(ex[0], ex[1], logx), ry = lim(ex[2], ex[3], logy);
    // yaxis7 es el violin del UITI y yaxis9 el de eventos: cada uno sigue el log de su
    // propia variable, no el del eje en que esta dibujado.
    // Los titulos de barras y violines dicen cuantas muestras resumen: dos rangos con
    // reparto parecido se leen igual si no se sabe que uno tiene la mitad de circuitos.
    var nMuestras = conteos[0] + conteos[1] + conteos[2] + conteos[3];
    var titulosN = {};
    ['barras', 'violinU', 'violinN'].forEach(function (k) {
      titulosN[CTX.ejesN[k] + '.title.text'] = CTX.titulosN[k] + ' (n = ' + nMuestras + ')';
    });
    Plotly.relayout(gd, titulosN);
    Plotly.relayout(gd, {'xaxis.type': tx, 'xaxis3.type': tx,
                         'yaxis3.type': ty, 'yaxis4.type': ty,
                         'yaxis7.type': ty, 'yaxis9.type': tx,
                         // xaxis3/yaxis3 son los del scatter y xaxis/yaxis4 los de sus
                         // marginales: los cuatro comparten los limites fijos.
                         'xaxis.range': rx, 'xaxis3.range': rx,
                         'yaxis3.range': ry, 'yaxis4.range': ry});

    var n = conteos.reduce(function (s, v) { return s + v; }, 0);
    d.getElementById('ag-aviso').textContent =
      'Rango efectivo: ' + CTX.meses[a] + ' a ' + CTX.meses[b] +
      ' (ajustado a meses completos) \\u2014 ' + n + ' circuitos con eventos en el periodo.';
  }

  ['ag-desde', 'ag-hasta'].forEach(function (id) {
    var el = d.getElementById(id);
    if (el) { el.addEventListener('change', aplicar); }
  });
  var boton = d.getElementById('ag-csv');
  if (boton) { boton.addEventListener('click', descargar); }
  aplicar();
})();
</script>
''' % json.dumps(CONTEXTO, separators=(',', ':'))

    # include_plotlyjs=True embebe plotly.js en esta misma salida: el panel, la figura y su
    # libreria viajan juntos, asi el cuaderno se ve igual exportado a HTML o en nbviewer.
    # `default_width='100%'` solo surte efecto porque la figura NO trae `width` (ver su
    # layout); junto a `config.responsive` hace que el tablero ocupe el ancho disponible y
    # se reajuste al redimensionar la ventana.
    FIGURA_HTML = pio.to_html(fig, include_plotlyjs=True, full_html=False, div_id=DIV_FIGURA,
                              default_width='100%', config={'responsive': True})

    PANEL_CIRCUITOS = PANEL_HTML + FIGURA_HTML + PANEL_JS

    def tabla_etiquetas(desde=None, hasta=None, log_x=LOG_X, log_y=LOG_Y, prep=PREPROCESO):
        """Etiqueta de cada circuito para una configuracion, como DataFrame listo para CSV.

    Es el camino reproducible del boton "Descargar etiquetas (CSV)" del panel: mismo
    esquema, mismo orden y las mismas funciones de agrupamiento, para que el archivo que
    baja el navegador y el que escribe el kernel no puedan divergir.
    """
        etiquetas_mes = [str(m) for m in MESES]
        i = etiquetas_mes.index(desde) if desde else 0
        j = etiquetas_mes.index(hasta) if hasta else len(MESES) - 1
        if i > j:
            i, j = j, i

        agrupada, _ = agrupar(tabla_circuitos(i, j), (log_x, log_y), prep)
        return (
            pd.DataFrame({
                # El periodo si va en cada fila: sin el, la etiqueta no significa nada. La escala
                # y el preproceso quedan solo en el nombre del archivo.
                'desde': str(MESES[i].to_timestamp().date()),
                'hasta': str(MESES[j].to_timestamp(how='end').date()),
                'circuito': agrupada['CIRCUITO'],
                'etiqueta': agrupada['grupo'].map(dict(enumerate(NOMBRES_GRUPOS))),
                'num_eventos': agrupada['num_eventos'].astype(int),
                'uiti_acumulado': agrupada['uiti_acumulado'].round(2),
            })
            .sort_values('uiti_acumulado', ascending=False)
            .reset_index(drop=True)
        )


    def guardar_etiquetas(destino=None, **config):
        """Escribe tabla_etiquetas(**config) en reports/reportescircuitos/artifacts/."""
        tabla = tabla_etiquetas(**config)
        if destino is None:
            # La escala y el preproceso ya no son columnas, asi que el nombre del archivo es
            # el unico lugar donde queda registrado en que espacio se corrio K-Means.
            fila = tabla.iloc[0]
            log_x, log_y = config.get('log_x', LOG_X), config.get('log_y', LOG_Y)
            destino = (REPO_ROOT / 'reports' / 'reportescircuitos' / 'artifacts' /
                       f'etiquetas_circuitos_{fila["desde"][:7]}_{fila["hasta"][:7]}'
                       f'_x{"log" if log_x else "lin"}_y{"log" if log_y else "lin"}'
                       f'_{config.get("prep", PREPROCESO)}.csv')
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tabla.to_csv(destino, index=False)
        return destino


    # Por defecto exporta la misma configuracion con que arranca la figura.
    etiquetas = tabla_etiquetas()
    ruta_csv = guardar_etiquetas()
    print(f'{len(etiquetas)} circuitos -> {_corta(ruta_csv, REPO_ROOT)}')
    print(etiquetas['etiqueta'].value_counts().reindex(NOMBRES_GRUPOS).to_string())
    etiquetas.head()

    from scipy.stats import gaussian_kde as _gaussian_kde_control

    # --- matriz vano x mes -------------------------------------------------------------------
    # El JS suma los meses del rango elegido. Para un conteo y una suma eso es exacto, y evita
    # mandar 21 copias de las coordenadas de 27.390 vanos.
    # Segunda lectura del CSV, ahora con FID_VANO. Reusa `leer_eventos` de la celda de carga.
    _COLS_VANO = ['CIRCUITO', 'FID_VANO', 'UITI_VANO', 'FECHA']
    _vano = leer_eventos(_COLS_VANO)
    _vano['FECHA'] = pd.to_datetime(_vano['FECHA'], errors='coerce')
    _vano['UITI_VANO'] = pd.to_numeric(_vano['UITI_VANO'], errors='coerce').fillna(0.0)
    # FID_VANO llega numerico con sufijo '.0' inconsistente entre filas; se normaliza como string
    # igual que `chec_local_interpreter.plotting._norm_map_id`, para no duplicar vanos por formato.
    _vano['FID_VANO'] = (_vano['FID_VANO'].astype('string').str.strip()
                         .str.replace(r'\.0$', '', regex=True))
    _vano['MES'] = _vano['FECHA'].dt.to_period('M')

    VANOS = sorted(_vano['FID_VANO'].unique())
    CIRCUITO_DE_VANO = (_vano.drop_duplicates('FID_VANO').set_index('FID_VANO')['CIRCUITO']
                        .reindex(VANOS).tolist())

    _n_mes = (_vano.pivot_table(index='FID_VANO', columns='MES', values='UITI_VANO', aggfunc='count')
              .reindex(VANOS).reindex(columns=MESES).fillna(0).astype(int))
    _u_mes = (_vano.pivot_table(index='FID_VANO', columns='MES', values='UITI_VANO', aggfunc='sum')
              .reindex(VANOS).reindex(columns=MESES).fillna(0.0).round(4))
    # 4 decimales, no 6: el redondeo se hace EN EL ORIGEN y no al serializar, porque la
    # pertenencia que vale en todos lados sale de aplicar la regla de centroide mas cercano
    # a los MISMOS numeros que recibe el navegador (ver el docstring de geometria_vanos).
    # Medido sobre los 8 espacios y la ventana completa: con 4 decimales la mascara de vanos
    # con eventos es identica y ningun vano cambia de grupo. Con 3 ya NO -- los UITI por
    # debajo de 0.0005 caen a cero y esos vanos desaparecen del tablero, porque el filtro es
    # u > 0. Ese es el piso, no una preferencia. Ademas el CSV de etiquetas ya emitia 4.
    N_MES, U_MES = _n_mes.to_numpy(), _u_mes.to_numpy()

    print(f'{len(VANOS):,} vanos x {len(MESES)} meses | '
          f'{len(_vano):,} eventos | {_vano["CIRCUITO"].nunique()} circuitos')
    print('eventos por vano en el rango completo -> mediana '
          f'{int(np.median(N_MES.sum(axis=1)))}, con un solo evento '
          f'{int((N_MES.sum(axis=1) == 1).sum()):,}')

    FRONTERA = []   # (puntos que cambian de grupo por el redondeo, total)


    def geometria_vanos(n, u, log_x, log_y, prep):
        """K-Means a 4 grupos sobre los vanos; devuelve solo la geometria de la particion.

    Las etiquetas no se embeben: el JS las deriva de los centroides con la regla de
    centroide mas cercano. Para que eso sea legitimo, la pertenencia que vale en TODOS
    lados -- puntos del mapa, contorno y CSV -- es la que sale de esa misma regla aplicada
    a la geometria YA REDONDEADA que se envia. Asi ningun punto puede quedar pintado del
    lado equivocado de su propia frontera.
    """
        X = np.column_stack([n, u]).astype(float)
        if log_x:
            X[:, 0] = np.log10(X[:, 0])
        if log_y:
            X[:, 1] = np.log10(X[:, 1])

        escalador = PREPROCESOS[prep]().fit(X)
        Z = escalador.transform(X)
        modelo = KMeans(n_clusters=4, random_state=SEMILLA, n_init=10).fit(Z)

        if prep == 'minmax':
            offset, scale = escalador.data_min_, escalador.data_range_
        else:
            offset, scale = escalador.mean_, escalador.scale_
        offset, scale = np.round(offset, 6), np.round(scale, 6)
        centros = np.round(modelo.cluster_centers_, 6)

        def pertenencia(centroides):
            Zr = (X - offset) / scale
            return (((Zr[:, None, :] - centroides[None, :, :]) ** 2).sum(axis=2)).argmin(axis=1)

        cruda = pertenencia(centros)

        # Control contra scikit-learn. No se exige igualdad exacta: un punto que cae justo
        # sobre una frontera de Voronoi puede cruzarla con el redondeo a 1e-6. Lo que no puede
        # pasar es que difieran muchos, que seria una geometria mal armada.
        difieren = int((cruda != modelo.predict(Z)).sum())
        FRONTERA.append((difieren, len(cruda)))
        assert difieren <= max(5, int(0.001 * len(cruda))), (
            f'{difieren} de {len(cruda)} puntos no coinciden con predict(): '
            'eso ya no es un empate de frontera')

        ocupacion = np.bincount(cruda, minlength=4)
        assert ocupacion.min() > 0, f'K-Means dejo un grupo vacio: {ocupacion.tolist()}'

        # El id que devuelve K-Means es arbitrario: el nombre del grupo se asigna por el
        # ranking de la MEDIANA del UITI acumulado, de menor a mayor. Reordenar los centroides
        # no cambia cual es el mas cercano, asi que la pertenencia sigue siendo la misma.
        orden = list(np.argsort([np.median(u[cruda == c]) for c in range(4)]))
        return {
            'logs': [bool(log_x), bool(log_y)],
            'offset': offset.tolist(),
            'scale': scale.tolist(),
            'centroides': centros[orden].tolist(),
        }


    # K-Means se ajusta UNA sola vez por espacio, sobre la ventana temporal completa, igual
    # que en el tablero de circuitos. Los centroides quedan fijos y cambiar el rango solo
    # reevalua a que grupo cae cada vano; las fronteras de Voronoi no se mueven.
    _n_full = N_MES.sum(axis=1)
    _u_full = U_MES.sum(axis=1)
    _full = (_n_full > 0) & (_u_full > 0)
    GEOMETRIAS_VANO = {
        str(e): geometria_vanos(_n_full[_full], _u_full[_full], log_x, log_y, prep)
        for e, (log_x, log_y, prep) in enumerate(ESPACIOS)
    }

    _peor, _tot = max(FRONTERA, key=lambda p: p[0]), sum(p[0] for p in FRONTERA)
    print(f'K-Means ajustado una vez (espacio fijo, sobre la ventana completa); '
          f'los {len(RANGOS)} rangos reusan esos centroides')
    print(f'puntos sobre la frontera que el redondeo mueve: {_tot} en total, '
          f'peor caso {_peor[0]} de {_peor[1]:,}')

    # Control del KDE que se reimplementa en JavaScript: mismo ancho de banda de Scott que usa
    # scipy, comparado sobre un caso real para que las densidades del panel no sean otra cosa.
    _m = (N_MES.sum(axis=1) > 0) & (U_MES.sum(axis=1) > 0)
    _v = U_MES.sum(axis=1)[_m][:2000]
    _grid = np.linspace(_v.min(), _v.max(), 5)
    _scipy = _gaussian_kde_control(_v)(_grid)
    _bw = np.std(_v, ddof=1) * len(_v) ** (-0.2)
    _propio = np.array([np.exp(-0.5 * ((g - _v) / _bw) ** 2).sum() / (len(_v) * _bw * np.sqrt(2 * np.pi))
                        for g in _grid])
    print(f'KDE propio vs scipy: error relativo maximo '
          f'{np.max(np.abs(_propio - _scipy) / _scipy):.2e}')

    # Misma estructura de trazas que el tablero de circuitos: 1 contorno + 4 scatter +
    # 1 barra de conteo + 1 de porcentaje + 4 del top 10 + 4 violines + 2 del ranking.
    fig_vano = make_subplots(
        # DOS filas y TRES columnas, con las cinco casillas ocupadas.
        #
        #   fila 1:  barras por grupo | dispersion vano x ventana | top 10 Medio-Alto+Alto
        #   fila 2:  violines de UITI | ranking de circuitos, sobre esas dos columnas
        #
        # Arriba queda la lectura por VANO -- cuantos hay en cada grupo, donde caen en el
        # plano eventos x UITI, y que circuitos concentran los peores -- y abajo la lectura
        # por distribucion y por circuito. El ranking sigue justo debajo de la dispersion y
        # sobre sus mismas dos columnas: sus 184 barras necesitan ese ancho, y alinearlas
        # con la nube es lo que deja leer las dos como una sola cosa.
        #
        # Se fueron las dos densidades marginales -- la curva sobre el eje x y la del eje y --
        # con sus ocho trazas. Repetian en forma lo que la dispersion ya dice con sus puntos,
        # y cada una se llevaba una fila o una columna enteras del tablero.
        rows=2, cols=3,
        # La fila de arriba se lleva algo mas: la dispersion es la pieza grande, y el top 10
        # apila cuatro clases sobre diez categorias.
        row_heights=[0.55, 0.45],
        # La columna 1 son cuatro categorias (los cuatro grupos) y no necesita ancho; el que
        # sobra se lo lleva la dispersion. El top 10 se queda con 0.34 porque sus nombres de
        # circuito van sobre el eje y, y ese margen lo pide `automargin`.
        column_widths=[0.24, 0.42, 0.34],
        # El horizontal se queda en 0.075: las columnas no se tocan.
        # El VERTICAL sube a 0.14 porque es una FRACCION del area de dibujo, y al
        # bajar el area a la mitad se encogia de 110 px a 55. Lo que tiene que caber
        # ahi -- el rotulo de eje x de la fila 1, el titulo de la fila 2 y su
        # subtitulo -- es TEXTO, y el texto no se encoge: a 55 px se pisaban.
        # 0.14 sobre los 788 px del area nueva son los mismos ~110 px de antes.
        horizontal_spacing=0.075, vertical_spacing=0.14,
        specs=[
            [{}, {}, {}],
            [{}, {'colspan': 2}, None],
        ],
        # En orden de lectura sobre las casillas que SI llevan subplot: (1,1) barras,
        # (1,2) dispersion, (1,3) top 10, (2,1) violines, (2,2) ranking. Plotly los reparte
        # por FILAS y no por nombre: reordenar la rejilla sin reordenar esta tupla le pone a
        # cada panel el titulo del vecino, sin dar error.
        subplot_titles=('Vanos por grupo', '',
                        'Top 10 Medio-Alto + Alto',
                        'UITI acumulado',
                        'Grupos Circuitos: Vanos en clase Medio-Alto y Alto por circuito'),
    )

    fig_vano.add_trace(go.Contour(                                   # 0: membresia
        z=[[0, 0], [0, 0]], x=[0, 1], y=[0, 1],
        colorscale=ESCALA_CONTORNO, zmin=-0.5, zmax=3.5, showscale=False,
        opacity=0.28, hoverinfo='skip', line=dict(width=1.2, color='rgba(120,20,20,0.6)'),
        contours=dict(start=-0.5, end=3.5, size=1, coloring='fill'), showlegend=False,
    ), row=1, col=2)
    for g in range(4):                                               # 1-4: scatter
        fig_vano.add_trace(go.Scattergl(
            x=[], y=[], mode='markers', name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
            marker=dict(size=4, color=COLORES_GRUPOS[g], opacity=0.6),
            hovertext=[], hovertemplate='%{hovertext}<extra></extra>',
        ), row=1, col=2)
    fig_vano.add_trace(go.Bar(                                       # 13: conteo
        x=NOMBRES_GRUPOS, y=[0] * 4, text=[0] * 4, textposition='outside',
        marker=dict(color=COLORES_GRUPOS, line=dict(width=0.5, color='rgba(60,60,60,0.6)')),
        showlegend=False, cliponaxis=False,
        hovertemplate='%{x}: %{y} vanos<extra></extra>',
    ), row=1, col=1)
    # El porcentaje va en una traza aparte, como en el tablero de circuitos: una barra tiene un
    # solo par `text`/`textposition`, asi que el conteo de afuera y el porcentaje de adentro no
    # pueden salir de la misma. El texto se ancla a media altura de cada barra.
    fig_vano.add_trace(go.Scatter(                                   # 14: porcentaje adentro
        x=NOMBRES_GRUPOS, y=[0] * 4, mode='text', text=[''] * 4,
        textposition='middle center',
        textfont=dict(size=11, color=['rgb(40,10,12)', 'rgb(40,10,12)', 'white', 'white']),
        showlegend=False, hoverinfo='skip',
    ), row=1, col=1)
    # 15-18: top 10 de circuitos por vanos en las DOS clases criticas, una traza por clase,
    # APILADAS y en porcentaje. La pregunta que responde no es "cuantos vanos tiene" sino
    # "como se reparte ese circuito entre las cuatro clases", asi que cada barra suma 100%% y
    # los circuitos se pueden comparar aunque tengan tamanos muy distintos. El orden y los
    # valores los recalcula el JS con el rango de fechas elegido.
    # `width` en unidades de categoria: 0.55 deja casi la mitad del paso como aire entre
    # barras. El `bargap` del layout no sirve aqui -- lo comparten con las barras verticales
    # de conteo, que si necesitan su grosor.
    # El porcentaje va DENTRO de cada tramo. Los dos grupos claros llevan texto oscuro y los
    # dos oscuros texto blanco, igual que en la barra de conteo. Los tramos angostos los
    # blanquea el JS antes de mandarlos: `insidetextfont` no puede achicar por debajo de lo
    # legible, y Plotly, cuando el texto no cabe, lo saca AFUERA de la barra, que en una
    # apilada cae encima del tramo vecino.
    COLOR_TEXTO_GRUPO = ['rgb(40,10,12)', 'rgb(40,10,12)', 'white', 'white']
    for g in range(4):                                               # 15-18: top 10 circuitos
        fig_vano.add_trace(go.Bar(
            x=[], y=[], orientation='h', width=0.55,
            name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
            marker=dict(color=COLORES_GRUPOS[g], line=dict(width=0.5, color='rgba(60,60,60,0.6)')),
            text=[], texttemplate='%{text}', textposition='inside', insidetextanchor='middle',
            insidetextfont=dict(size=10, color=COLOR_TEXTO_GRUPO[g]), cliponaxis=False,
            showlegend=False, hovertext=[], hovertemplate='%{hovertext}<extra></extra>',
        ), row=1, col=3)

    for fila, etiqueta in [(2, 'UITI acumulado')]:                   # 15-18: violines UITI
        for g in range(4):
            fig_vano.add_trace(go.Violin(
                x=[], y=[], name=NOMBRES_GRUPOS[g], legendgroup=NOMBRES_GRUPOS[g],
                showlegend=False, line=dict(color='rgba(90,15,20,0.85)', width=1),
                fillcolor=COLORES_GRUPOS[g], opacity=0.85,
                box_visible=True, meanline_visible=False, points=False, spanmode='hard',
                hovertemplate=f'%{{x}} -- {etiqueta}: %{{y:,.1f}}<extra></extra>',
            ), row=fila, col=1)

    # --- Fila 2, columnas 2-3: vanos en las DOS clases criticas por circuito --------------
    # El conteo y el orden suman Medio-Alto Y Alto: un circuito con muchos vanos a un paso de
    # la clase peor es tan accionable como uno que ya los tiene ahi, y mirando solo Alto esa
    # poblacion quedaba invisible.
    # Entran TODOS los circuitos de la base, incluidos los que no tuvieron ningun evento en la
    # ventana: quedan en cero, a la izquierda, y cuentan para los percentiles. Excluirlos
    # sesgaba los cortes hacia arriba, tanto mas cuanto mas corto el rango.
    # El color va por rango del propio conteo, de menor a mayor, y ahora es EL MISMO semaforo
    # que los grupos. Antes era una paleta aparte, para que nadie leyera una equivalencia con
    # la rampa de rojos del agrupamiento; con los grupos ya en semaforo ese argumento se da
    # vuelta: dos semaforos casi iguales en la misma figura se leen como un error, no como una
    # distincion. Y el titulo de este panel ya nombra sus cuatro rangos por RIESGO, con las
    # mismas cuatro palabras que los grupos, asi que compartir la escala es lo honesto.
    # Lo que sigue significando otra cosa es la UNIDAD: alli un vano, aqui un circuito.
    COLORES_CUARTIL = list(COLORES_GRUPOS)

    fig_vano.add_trace(go.Bar(                                       # 23: conteo por circuito
        x=[], y=[], marker=dict(color=[], line=dict(width=0.4, color='rgba(60,60,60,0.5)')),
        showlegend=False, cliponaxis=False,
        hovertext=[], hovertemplate='%{hovertext}<extra></extra>',
    ), row=2, col=2)
    # Las tres divisiones de cuartil van en UNA sola traza de lineas, separadas por null.
    # Se resuelven con coordenadas numericas sobre el eje de categorias (i + 0.5 cae entre la
    # categoria i y la i+1), que es como se marca una frontera sin inventar una categoria.
    fig_vano.add_trace(go.Scatter(                                   # 24: divisiones Q1/Q2/Q3
        x=[], y=[], mode='lines', line=dict(color='rgba(40,40,40,0.55)', width=1.2, dash='dot'),
        showlegend=False, hoverinfo='skip',
    ), row=2, col=2)

    fig_vano.update_layout(
        title=dict(
            text='Agrupamiento de vanos por UITI acumulado y número de eventos'
                 '<br><sup>K-Means (k=4) sobre 27.390 vanos; grupos nombrados por el ranking de la '
                 'mediana del UITI acumulado</sup>',
            x=0.5, xanchor='center', yref='container', y=0.97, yanchor='top',
            # A la MITAD: 17, que es ademas el defecto de Plotly. Estuvo en 34 -- el doble
            # del defecto -- para que pesara como el titulo de un informe, y a ese tamanio
            # se comia tres renglones antes del primer panel diciendo lo que el nombre de
            # la aplicacion en el menu ya dice.
            font=dict(size=17),
        ),
        legend=dict(title_text='', orientation='h', x=0.5, xanchor='center', y=1.02, yanchor='bottom'),
        # El margen baja CON el titulo. Estos 175 se eligieron contra un titulo de 34 px:
        # con 120 la leyenda horizontal -- anclada a y=1.02 del area de dibujo -- subia
        # hasta pisar el subtitulo, medidos 7 px de solapamiento. Con el titulo en 17 esa
        # banda sobra, y `margin.t` esta en PIXELES: no encoge solo. Los 140 se comprueban
        # contra el navegador en `test_rotulos_sin_traslape`.
        margin=dict(t=140, r=30, b=60, l=90),
        # SIN `width`, misma razon que el primer tablero (ver la celda de su layout).
        # `barmode='stack'` es lo que apila las 4 clases de las barras horizontales. No afecta
        # a la barra de conteo por grupo: esa es UNA sola traza, y apilar una traza sola no
        # cambia nada.
        barmode='stack',
        # 1023 y no 1700: las filas van a la MITAD de alto y las columnas se quedan
        # como estaban. Bajar `row_heights` no habria servido -- son fracciones, se
        # renormalizan y dividirlas por dos no mueve un pixel; lo que manda es este
        # `height`.
        # Medido a 1700: area de dibujo 1465 px (1700 - 175 - 60 de margen), fila 1 =
        # 745, fila 2 = 610, y los 110 restantes la separacion entre filas. Las filas
        # a la mitad son 372,5 + 305 = 677,5.
        # De ahi salen los DOS numeros que no se pueden elegir por separado:
        #   area  = 677,5 (filas) + 110 (separacion, que NO se encoge: es texto) = 788
        #   height = 788 + 235 (margenes, en PIXELES, no se reparten)            = 1023
        # Partir 1700 por dos habria dado 850, y con el las filas caian al 42% -- no a
        # la mitad -- porque una figura la mitad de alta le paga a los margenes una
        # tajada doble. Y quedarse en 968 (el numero correcto si la separacion pudiera
        # encogerse) pisaba el rotulo del eje x de la fila 1 contra el titulo de la 2.
        height=1023, template='plotly_white', bargap=0.45, violingap=0.3,
    )
    fig_vano.update_xaxes(title_text='Número de eventos por vano', row=1, col=2)
    fig_vano.update_yaxes(title_text='UITI acumulado por vano', row=1, col=2)
    # Eje de las barras horizontales: porcentaje 0-100 fijo, para que las 10 barras se lean
    # como proporciones comparables y no se reencuadren al cambiar de rango.
    fig_vano.update_xaxes(title_text='% de vanos del circuito', range=[0, 100],
                          ticksuffix='%', row=1, col=3)
    fig_vano.update_yaxes(title_text='', automargin=True, row=1, col=3)
    # `ticklabelstandoff` aparta las marcas del eje y 8 px del area de dibujo. Sin el, el
    # '0' del origen y la primera etiqueta de circuito -- vertical, pegada al eje -- se
    # tocaban por 6 px, y solo a 1.280 y 1.512: a 1.900 el panel es mas ancho y no pasaba.
    fig_vano.update_yaxes(title_text='Vanos Medio-Alto + Alto', rangemode='tozero',
                          ticklabelstandoff=8, row=2, col=2)
    # Eje LINEAL, no de categorias, aunque lo que se rotula sean nombres de circuito. En un
    # eje de categorias Plotly interpreta un x numerico como una categoria NUEVA: las tres
    # divisiones de cuartil (11.5, 22.5, 33.5) se dibujaban como tres categorias extra
    # pegadas al final del eje en vez de caer entre las barras. Con el eje lineal las barras
    # van en 0..n-1, la division en k-0.5 cae donde tiene que caer, y los nombres se ponen
    # con tickvals/ticktext que el JS reescribe en cada repintado.
    fig_vano.update_xaxes(title_text='Circuitos ordenados por vanos en Medio-Alto + Alto',
                          tickangle=-90, tickfont_size=8, automargin=True,
                          showgrid=False, row=2, col=2)
    fig_vano.update_yaxes(title_text='Vanos', rangemode='tozero', row=1, col=1)
    fig_vano.update_yaxes(title_text='UITI acumulado', row=2, col=1)
    # Titulos de subplot al DOBLE (eran 12): el tablero se mira a pantalla completa y a 12 px
    # los rotulos de cada casilla se perdian frente a la figura.
    FUENTE_SUBTITULO = 16
    for _anotacion in fig_vano.layout.annotations:
        _anotacion.font.size = FUENTE_SUBTITULO


    def _clave_eje_vano(traza, cual):
        # OJO: `traza.y` son los DATOS; la referencia de eje vive en `traza.yaxis` ('y', 'y3'...).
        ref = getattr(traza, f'{cual}axis') or cual
        return f'{cual}axis' + ref[1:]


    # Indices declarados una sola vez y enviados al JS, para que insertar una traza no deje
    # todos los restyle escribiendo en la equivocada sin que nada falle a la vista.
    # Titulos que el panel reescribe con el numero de muestras. El indice se resuelve por TEXTO:
    # si alguien reordena los subplots sigue siendo el correcto, y si cambia el texto esto falla
    # al generar en vez de reescribir el titulo equivocado.
    TITULOS_N_VANO = {}
    for _clave, _texto in [('barras', 'Vanos por grupo'),
                           ('top', 'Top 10 Medio-Alto + Alto'),
                           ('altoCirc', 'Grupos Circuitos: Vanos en clase Medio-Alto y Alto por circuito'),
                           ('violinU', 'UITI acumulado')]:
        _pos = [i for i, _a in enumerate(fig_vano.layout.annotations) if _a.text == _texto]
        assert len(_pos) == 1, (_texto, _pos)
        TITULOS_N_VANO[_clave] = [_pos[0], _texto]

    # Sin las ocho trazas de las densidades marginales, todo lo que venia detras corre ocho
    # lugares. Los indices se declaran aqui y viajan al JS, asi que este bloque y el orden de
    # los `add_trace` de arriba son UNA sola cosa: si dejan de coincidir, cada `restyle`
    # escribe en la traza equivocada sin que nada falle a la vista.
    IDX_VANO = {'contorno': 0, 'mapa': [1, 2, 3, 4], 'barras': 5, 'pct': 6,
                'barrasTop': [7, 8, 9, 10], 'violinUiti': [11, 12, 13, 14],
                'altoCircuito': 15, 'cuartiles': 16}
    assert len(fig_vano.data) == 17
    assert fig_vano.data[IDX_VANO['altoCircuito']].type == 'bar'
    assert fig_vano.data[IDX_VANO['cuartiles']].mode == 'lines'
    assert all(fig_vano.data[i].type == 'bar' and fig_vano.data[i].orientation == 'h'
               for i in IDX_VANO['barrasTop']), 'las 4 del top 10 son barras horizontales'
    assert fig_vano.data[IDX_VANO['contorno']].type == 'contour'
    assert all(fig_vano.data[i].type == 'scattergl' for i in IDX_VANO['mapa'])
    assert all(fig_vano.data[i].type == 'violin' for i in IDX_VANO['violinUiti'])
    assert fig_vano.data[IDX_VANO['barras']].type == 'bar'
    assert fig_vano.data[IDX_VANO['pct']].mode == 'text'

    EJES_VANO = {
        'mapaX': _clave_eje_vano(fig_vano.data[IDX_VANO['mapa'][0]], 'x'),
        'mapaY': _clave_eje_vano(fig_vano.data[IDX_VANO['mapa'][0]], 'y'),
        'barras': _clave_eje_vano(fig_vano.data[IDX_VANO['barras']], 'y'),
        'violinUiti': _clave_eje_vano(fig_vano.data[IDX_VANO['violinUiti'][0]], 'y'),
        'topY': _clave_eje_vano(fig_vano.data[IDX_VANO['barrasTop'][0]], 'y'),
        'altoY': _clave_eje_vano(fig_vano.data[IDX_VANO['altoCircuito']], 'y'),
        'altoX': _clave_eje_vano(fig_vano.data[IDX_VANO['altoCircuito']], 'x'),
    }
    print(f'{len(fig_vano.data)} trazas | ejes: {EJES_VANO}')

    DIV_VANO = 'agrupamiento-vanos'

    # --- Compactado del contexto ---------------------------------------------------------
    # Tres compresiones sin perdida sobre lo que viaja al navegador (medido: 2.005 KB -> 1.438
    # KB, un 28%% menos de las cuatro llaves grandes):
    #
    #  1. `uMes` con los ceros exactos como ENTERO. El 62,8%% de la matriz vano x mes son
    #     ceros, y json.dumps escribe "0.0" donde alcanza "0". Los no-cero siguen con sus 4
    #     decimales, y el JS los suma igual -- en JavaScript no hay int contra float.
    #  2. `circuitos` como PALETA. Son 208 nombres distintos repetidos sobre 27.390 vanos;
    #     viaja la lista de nombres una vez mas un indice entero por vano.
    #  3. `vanos` como entero cuando los ids son numericos, que ahorra las comillas. Se
    #     comprueba antes: si algun id trae letras se quedan como cadena, porque la base
    #     puede cambiar de formato de identificador.
    def _ceros_enteros(fila):
        """Los ceros exactos salen como 0 y no como 0.0; el resto queda igual."""
        return [0 if v == 0 else float(v) for v in fila]


    _U_MES_JSON = [_ceros_enteros(f) for f in U_MES.tolist()]
    _CIRC_UNICOS = sorted(set(CIRCUITO_DE_VANO))
    _CIRC_POS = {c: i for i, c in enumerate(_CIRC_UNICOS)}
    _VANOS_JSON = ([int(v) for v in VANOS] if all(str(v).isdigit() for v in VANOS)
                   else list(VANOS))

    CONTEXTO_VANO = {
        'div': DIV_VANO,
        'meses': [str(m) for m in MESES],
        'finMes': [str(m.to_timestamp(how='end').date()) for m in MESES],
        'rangos': RANGOS,
        'espacios': [[bool(lx), bool(ly), prep] for lx, ly, prep in ESPACIOS],
        'grupos': NOMBRES_GRUPOS,
        'coloresCuartil': COLORES_CUARTIL,
        'vanos': _VANOS_JSON,
        # `circuitos` es ahora el INDICE en `circuitosNombres`, no el nombre. El JS lo
        # resuelve con circDe(v); no leer CTX.circuitos[v] directamente.
        'circuitosNombres': _CIRC_UNICOS,
        'circuitos': [_CIRC_POS[c] for c in CIRCUITO_DE_VANO],
        'nMes': N_MES.tolist(),
        'uMes': _U_MES_JSON,
        'geometrias': GEOMETRIAS_VANO,
        'idx': IDX_VANO,
        'ejes': EJES_VANO,
        'titulos': TITULOS_N_VANO,
        'resolucion': 80,
        'extension': [float(N_MES.sum(axis=1)[_full].min()), float(N_MES.sum(axis=1)[_full].max()),
                      float(U_MES.sum(axis=1)[_full].min()), float(U_MES.sum(axis=1)[_full].max())],
    }

    PANEL_VANO_HTML = f'''
<div class="panel-agrup">
  <div><label for="va-desde">Desde</label>
       <input type="date" id="va-desde" min="{PRIMER_DIA}" max="{ULTIMO_DIA}" value="{PRIMER_DIA}"></div>
  <div><label for="va-hasta">Hasta</label>
       <input type="date" id="va-hasta" min="{PRIMER_DIA}" max="{ULTIMO_DIA}" value="{ULTIMO_DIA}"></div>
  <div><button type="button" id="va-csv">Descargar etiquetas (Excel)</button></div>
  <p class="panel-aviso" id="va-aviso"></p>
</div>
'''

    PANEL_VANO_JS = '''
<script type="text/javascript">
(function () {
  var CTX = %s;
  var d = document;
  var ESTADO = null;

  function idxMes(v) { var i = CTX.meses.indexOf((v || '').slice(0, 7)); return i < 0 ? null : i; }

  function idxRango(a, b) {
    for (var i = 0; i < CTX.rangos.length; i++) {
      if (CTX.rangos[i][0] === a && CTX.rangos[i][1] === b) return i;
    }
    return null;
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

  // El nombre del circuito de un vano. `CTX.circuitos[v]` trae el INDICE en
  // CTX.circuitosNombres, no el nombre: son 208 nombres para 27.390 vanos y repetirlos
  // costaba 200 KB del JSON. Un solo punto de resolucion para no equivocarse.
  function circDe(v) { return CTX.circuitosNombres[CTX.circuitos[v]]; }

  // Circuitos de la fila 5, en el orden dibujado. Vive fuera de aplicar() porque el
  // handler de resize necesita re-rotular sin recalcular nada.
  var CIRC_FILA5 = [];

  // Etiquetas del eje de la fila 5 adelgazadas segun el ancho REAL. Con 184 circuitos en
  // una ventana de 1000 px quedan 5,2 px por categoria y los nombres rotados se pisan;
  // con 1700 px hay 9,0 px y entran. Se calcula el paso a partir del ancho en pixeles del
  // subplot, no de un numero fijo, asi el mismo tablero sirve angosto y ancho. El nombre
  // completo siempre esta en el hover, que no depende de esto.
  var PX_POR_ETIQUETA = 10;

  function rotularFila5(gd) {
    if (!CIRC_FILA5.length) { return; }
    var eje = CTX.ejes.altoX, fl = gd._fullLayout || {};
    var dom = (fl[eje] || {}).domain || [0, 1];
    var anchoPx = (dom[1] - dom[0]) * (fl.width || 1200);
    var caben = Math.max(1, Math.floor(anchoPx / PX_POR_ETIQUETA));
    var paso = Math.max(1, Math.ceil(CIRC_FILA5.length / caben));
    var tv = [], tt = [];
    for (var k = 0; k < CIRC_FILA5.length; k += paso) { tv.push(k); tt.push(CIRC_FILA5[k]); }
    var cambio = {};
    cambio[eje + '.tickvals'] = tv;
    cambio[eje + '.ticktext'] = tt;
    Plotly.relayout(gd, cambio);
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

  // --- Libro .xlsx armado en el navegador ------------------------------------------
  // Sin librerias: el tablero es un archivo autocontenido y la app de Databricks corre
  // con CSP, asi que no puede traer SheetJS ni nada de un CDN. Un .xlsx es un ZIP de
  // partes XML, y el ZIP se escribe con metodo STORE (sin comprimir): es valido segun
  // la especificacion y evita tener que implementar DEFLATE a mano. Excel, LibreOffice
  // y openpyxl lo abren igual; a cambio el archivo pesa mas, cosa que aqui no importa.
  var CRC_TABLA = (function () {
    var t = new Uint32Array(256), c, n, k;
    for (n = 0; n < 256; n++) {
      c = n;
      for (k = 0; k < 8; k++) { c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1); }
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(u8) {
    var c = 0xFFFFFFFF;
    for (var i = 0; i < u8.length; i++) { c = CRC_TABLA[(c ^ u8[i]) & 0xFF] ^ (c >>> 8); }
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  // DEFLATE con la API nativa del navegador: `CompressionStream('deflate-raw')` produce
  // exactamente el flujo que el ZIP espera en el metodo 8, sin traer ninguna libreria.
  // Es asincrona, y por eso todo el camino de descarga lo es. Si el navegador no la
  // tiene (Chrome < 80, Safari < 16.4) se cae a STORE, que sigue dando un .xlsx valido
  // -- solo mas pesado. Medido sobre la ventana completa: 12,26 MB con STORE contra
  // 1,35 MB con DEFLATE.
  function desinflar(u8) {
    if (typeof CompressionStream === 'undefined') { return Promise.resolve(null); }
    var cs = new CompressionStream('deflate-raw');
    return new Response(new Blob([u8]).stream().pipeThrough(cs)).arrayBuffer()
      .then(function (buf) { return new Uint8Array(buf); })
      .catch(function () { return null; });
  }

  function zipDeflate(partes) {
    var enc = new TextEncoder();
    var crudos = partes.map(function (parte) {
      return {nom: enc.encode(parte.nombre), dat: enc.encode(parte.texto)};
    });
    return Promise.all(crudos.map(function (c) { return desinflar(c.dat); }))
      .then(function (comprimidos) {
        var locales = [], central = [], off = 0;
        crudos.forEach(function (c, k) {
          var comp = comprimidos[k], usaDeflate = comp !== null && comp.length < c.dat.length;
          var cuerpo = usaDeflate ? comp : c.dat;
          var metodo = usaDeflate ? 8 : 0;
          var crc = crc32(c.dat);              // el CRC es SIEMPRE del dato original
          var lh = new Uint8Array(30 + c.nom.length), dv = new DataView(lh.buffer);
          dv.setUint32(0, 0x04034b50, true);   // firma de cabecera local
          dv.setUint16(4, 20, true);           // version necesaria
          dv.setUint16(6, 0x0800, true);       // bit 11: nombres en UTF-8
          dv.setUint16(8, metodo, true);
          dv.setUint32(14, crc, true);
          dv.setUint32(18, cuerpo.length, true);
          dv.setUint32(22, c.dat.length, true);
          dv.setUint16(26, c.nom.length, true);
          lh.set(c.nom, 30);
          var cd = new Uint8Array(46 + c.nom.length), dc = new DataView(cd.buffer);
          dc.setUint32(0, 0x02014b50, true);   // firma de directorio central
          dc.setUint16(4, 20, true); dc.setUint16(6, 20, true);
          dc.setUint16(8, 0x0800, true); dc.setUint16(10, metodo, true);
          dc.setUint32(16, crc, true);
          dc.setUint32(20, cuerpo.length, true); dc.setUint32(24, c.dat.length, true);
          dc.setUint16(28, c.nom.length, true);
          dc.setUint32(42, off, true);         // desplazamiento de su cabecera local
          cd.set(c.nom, 46);
          locales.push(lh, cuerpo); central.push(cd);
          off += lh.length + cuerpo.length;
        });
        var tamCd = central.reduce(function (a, x) { return a + x.length; }, 0);
        var fin = new Uint8Array(22), df = new DataView(fin.buffer);
        df.setUint32(0, 0x06054b50, true);     // fin del directorio central
        df.setUint16(8, crudos.length, true); df.setUint16(10, crudos.length, true);
        df.setUint32(12, tamCd, true); df.setUint32(16, off, true);
        var todo = locales.concat(central, [fin]);
        var total = todo.reduce(function (a, x) { return a + x.length; }, 0);
        var out = new Uint8Array(total), pos = 0;
        todo.forEach(function (x) { out.set(x, pos); pos += x.length; });
        return out;
      });
  }

  function xmlEsc(v) {
    return String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function colLetra(i) {
    var s = '', r;
    i += 1;
    // El %% va duplicado: este bloque se arma con formateo de cadena de Python.
    while (i > 0) { r = (i - 1) %% 26; s = String.fromCharCode(65 + r) + s; i = (i - r - 1) / 26; }
    return s;
  }

  // Las cadenas van como inlineStr, no por tabla de cadenas compartidas: ahorra una parte
  // del paquete y aqui casi no hay texto repetido que compartir.
  function hojaXml(filas) {
    var out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
               '<sheetData>'];
    filas.forEach(function (fila, r) {
      var celdas = [];
      fila.forEach(function (v, c) {
        if (v === null || v === undefined || v === '') { return; }
        var ref = colLetra(c) + (r + 1);
        if (typeof v === 'number' && isFinite(v)) {
          celdas.push('<c r="' + ref + '"><v>' + v + '</v></c>');
        } else {
          celdas.push('<c r="' + ref + '" t="inlineStr"><is><t xml:space="preserve">' +
                      xmlEsc(v) + '</t></is></c>');
        }
      });
      out.push('<row r="' + (r + 1) + '">' + celdas.join('') + '</row>');
    });
    out.push('</sheetData></worksheet>');
    return out.join('');
  }

  function libroXlsx(hojas) {
    var NSR = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
    var CT = 'application/vnd.openxmlformats-officedocument.spreadsheetml';
    var cab = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
    var partes = [
      {nombre: '[Content_Types].xml', texto: cab +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/xl/workbook.xml" ContentType="' + CT + '.sheet.main+xml"/>' +
        hojas.map(function (h, i) {
          return '<Override PartName="/xl/worksheets/sheet' + (i + 1) +
                 '.xml" ContentType="' + CT + '.worksheet+xml"/>';
        }).join('') + '</Types>'},
      {nombre: '_rels/.rels', texto: cab +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="' + NSR + '/officeDocument" Target="xl/workbook.xml"/>' +
        '</Relationships>'},
      {nombre: 'xl/workbook.xml', texto: cab +
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="' +
        NSR + '"><sheets>' +
        hojas.map(function (h, i) {
          return '<sheet name="' + xmlEsc(h.nombre) + '" sheetId="' + (i + 1) +
                 '" r:id="rId' + (i + 1) + '"/>';
        }).join('') + '</sheets></workbook>'},
      {nombre: 'xl/_rels/workbook.xml.rels', texto: cab +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        hojas.map(function (h, i) {
          return '<Relationship Id="rId' + (i + 1) + '" Type="' + NSR +
                 '/worksheet" Target="worksheets/sheet' + (i + 1) + '.xml"/>';
        }).join('') + '</Relationships>'}
    ];
    hojas.forEach(function (h, i) {
      partes.push({nombre: 'xl/worksheets/sheet' + (i + 1) + '.xml', texto: hojaXml(h.filas)});
    });
    return zipDeflate(partes);
  }

  // Las dos hojas del libro, con lo que ya calculo aplicar(): no se recorre nada de nuevo.
  function hojasActuales() {
    var s = ESTADO, i, g;
    var fv = [['desde', 'hasta', 'vano', 'circuito', 'etiqueta', 'num_eventos',
               'uiti_acumulado']];
    var filas = [];
    for (g = 0; g < 4; g++) {
      for (i = 0; i < s.idxPorGrupo[g].length; i++) {
        var v = s.idxPorGrupo[g][i];
        filas.push({v: v, g: g, n: s.n[v], u: s.u[v]});
      }
    }
    filas.sort(function (p, q) { return q.u - p.u; });
    // `etiqueta` va en mayuscula sostenida, igual que `grupo_ranking` en la otra hoja: el
    // libro se lee en Excel, donde dos escrituras distintas de las mismas cuatro palabras
    // ('Medio-Alto' en una hoja y 'MEDIO-ALTO' en la otra) parecen dos vocabularios y
    // obligan a plegar mayusculas para cruzarlas. Se deriva de CTX.grupos en vez de
    // reescribir la lista, para que la leyenda del grafico siga siendo el unico origen de
    // los cuatro nombres; el grafico conserva la capitalizacion normal, que es lo que se
    // lee en pantalla.
    filas.forEach(function (f) {
      fv.push([s.desde, s.hasta, String(CTX.vanos[f.v]), circDe(f.v),
               CTX.grupos[f.g].toUpperCase(), f.n, f.u]);
    });
    // Hoja de circuitos, en el mismo orden que el ranking de las ultimas filas.
    // `grupo_ranking` lleva el NOMBRE de la banda del ranking -- BAJO, MEDIO, MEDIO-ALTO o
    // ALTO -- y queda VACIO en los circuitos que no entran al ranking por no tener ningun
    // vano en Medio-Alto ni en Alto.
    //
    // OJO al leer el libro: esa banda NO es el grupo de K-Means. Los grupos de K-Means
    // etiquetan VANOS y viven en la columna `etiqueta` de la hoja Vanos; estas bandas son
    // percentiles (P50/P75/P97) del numero de vanos criticos por circuito -- otra pregunta
    // sobre otra unidad. Los dos juegos de nombres coinciden palabra por palabra, asi que
    // lo que los distingue es la HOJA y el nombre de la columna, no el valor. En el grafico
    // si se conserva el prefijo "Riesgo", porque alli las dos escalas conviven a la vista.
    //
    // `vanos_medio_alto_mas_alto` se retiro: era exactamente vanos_medio_alto + vanos_alto,
    // las dos columnas que la preceden, asi que no aportaba nada que la hoja no tuviera.
    var fc = [['desde', 'hasta', 'circuito', 'vanos_bajo', 'vanos_medio',
               'vanos_medio_alto', 'vanos_alto', 'vanos_total',
               'uiti_acumulado', 'num_eventos', 'grupo_ranking']];
    var circs = Object.keys(s.porCirc).sort(function (a, b) {
      var ca = s.porCirc[a][2] + s.porCirc[a][3], cb = s.porCirc[b][2] + s.porCirc[b][3];
      return (cb - ca) || (a < b ? -1 : 1);
    });
    circs.forEach(function (c) {
      var q = s.porCirc[c], tot = q[0] + q[1] + q[2] + q[3];
      fc.push([s.desde, s.hasta, c, q[0], q[1], q[2], q[3], tot,
               s.uitiCirc[c], s.evCirc[c], s.rangoPorCirc[c] || '']);
    });
    return [{nombre: 'Vanos', filas: fv}, {nombre: 'Circuitos', filas: fc}];
  }

  function descargar() {
    if (!ESTADO) { return; }
    // libroXlsx es asincrono porque comprime con la API nativa del navegador.
    var boton = d.getElementById('va-csv');
    if (boton) { boton.disabled = true; }
    libroXlsx(hojasActuales()).then(function (bytes) {
      var url = URL.createObjectURL(new Blob([bytes],
        {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
      var a = d.createElement('a');
      a.href = url; a.download = ESTADO.nombre;
      d.body.appendChild(a); a.click(); d.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 0);
    }).finally(function () { if (boton) { boton.disabled = false; } });
  }

  function aplicar() {
    var gd = d.getElementById(CTX.div);
    if (!gd || !gd._fullLayout) { return setTimeout(aplicar, 120); }

    var a = idxMes(d.getElementById('va-desde').value);
    var b = idxMes(d.getElementById('va-hasta').value);
    if (a === null) a = 0;
    if (b === null) b = CTX.meses.length - 1;
    if (a > b) { var t = a; a = b; b = t; }
    // El espacio es fijo -- eje x lineal, eje y logaritmico, minmax -- y ya no hay
    // controles que lo cambien: `CTX.espacios` trae uno solo. Se lee de ahi y no de
    // constantes escritas aqui, para que el dibujo y el nombre del Excel no puedan
    // contradecir a la geometria con que se ajusto K-Means del lado de Python.
    var esp = CTX.espacios[0];
    var logx = esp[0], logy = esp[1], prep = esp[2];
    // La geometria tampoco depende del rango de fechas.
    var geo = CTX.geometrias['0'];
    if (!geo) { return; }

    // Sumar los meses del rango: para un conteo y una suma da exactamente lo mismo que
    // haber agregado el rango entero desde el CSV.
    var n = [], u = [], idxPorGrupo = [[], [], [], []];
    for (i = 0; i < CTX.vanos.length; i++) {
      var sn = 0, su = 0;
      for (var m = a; m <= b; m++) { sn += CTX.nMes[i][m]; su += CTX.uMes[i][m]; }
      n.push(sn); u.push(su);
      // Mismo filtro que Python: sin eventos o sin UITI el punto no existe en escala log.
      if (sn <= 0 || su <= 0) { continue; }
      idxPorGrupo[grupoDe(sn, su, geo)].push(i);
    }
    // Extremos FIJOS, de la ventana completa: los mismos sobre los que se ajustaron los
    // centroides. Recalcularlos por rango reencuadraba los ejes y el contorno.
    var minX = CTX.extension[0], maxX = CTX.extension[1];
    var minY = CTX.extension[2], maxY = CTX.extension[3];

    var mx = [], my = [], mt = [], conteos = [], vg = [], vy = [];
    for (var g = 0; g < 4; g++) {
      var xs = [], ys = [], ts = [], cats = [];
      for (i = 0; i < idxPorGrupo[g].length; i++) {
        var v = idxPorGrupo[g][i];
        xs.push(n[v]); ys.push(u[v]);
        // El UITI llega de sumar los meses del rango en coma flotante, asi que sin
        // formato el hover mostraba cosas como "1234.5678000000001". Un decimal y
        // separador de miles, igual que el `%%{y:,.1f}` del tablero de circuitos.
        ts.push('<b>' + CTX.vanos[v] + '</b><br>Circuito: ' + circDe(v) +
                '<br>Grupo: <b>' + CTX.grupos[g] + '</b>' +
                '<br>Eventos: ' + n[v].toLocaleString() +
                '<br>UITI acumulado: ' + u[v].toLocaleString(undefined,
                    {minimumFractionDigits: 1, maximumFractionDigits: 1}));
        cats.push(CTX.grupos[g]);
      }
      mx.push(xs); my.push(ys); mt.push(ts); conteos.push(xs.length);
      vg.push(cats); vy.push(ys);
    }

    Plotly.restyle(gd, {x: mx, y: my, hovertext: mt}, CTX.idx.mapa);
    // El porcentaje se calcula sobre el total dibujado, para que las cuatro cifras sumen
    // 100, y va DENTRO de la barra solo si la barra es lo bastante alta. En una barra muy
    // baja el texto de media altura cae sobre el eje y se encima con el nombre del grupo;
    // en ese caso se pega al conteo de afuera, que es donde si hay sitio.
    var totalV = conteos[0] + conteos[1] + conteos[2] + conteos[3];
    var maxC = Math.max.apply(null, conteos) || 1;
    var pctTxt = conteos.map(function (c) {
      // Simbolo duplicado: el bloque se arma con formateo de cadena.
      return totalV ? (100 * c / totalV).toFixed(1) + '%%' : '';
    });
    var bajo = conteos.map(function (c) { return c / maxC < 0.12; });
    Plotly.restyle(gd, {y: [conteos], text: [conteos.map(
      function (c, i) { return bajo[i] ? c + '  ' + pctTxt[i] : String(c); })]},
      [CTX.idx.barras]);
    Plotly.restyle(gd, {
      y: [conteos.map(function (c) { return c / 2; })],
      text: [pctTxt.map(function (p, i) { return bajo[i] ? '' : p; })],
    }, [CTX.idx.pct]);
    Plotly.restyle(gd, {x: vg, y: vy}, CTX.idx.violinUiti);

    // --- Top 10 de circuitos por vanos en Medio-Alto + Alto -------------------------
    // Se cuenta sobre los MISMOS grupos que se acaban de calcular para el scatter, asi
    // que el ranking responde al rango de fechas elegido y no a una foto
    // fija. Se muestra en PORCENTAJE y no en conteo porque la pregunta es como se
    // reparte cada circuito entre las cuatro clases: en conteo, un circuito grande
    // domina la escala y aplasta a los demas aunque tenga mejor proporcion.
    // Junto con el conteo por clase se acumulan, EN EL MISMO recorrido, el UITI y los
    // eventos de cada circuito sobre la ventana elegida. Salen de los mismos n[] y u[]
    // que alimentan el scatter, asi que no puede haber discrepancia entre lo que se ve y
    // lo que dice la etiqueta.
    var porCirc = {}, uitiCirc = {}, evCirc = {}, cc, tot, iv;
    for (g = 0; g < 4; g++) {
      for (i = 0; i < idxPorGrupo[g].length; i++) {
        iv = idxPorGrupo[g][i];
        cc = circDe(iv);
        if (!porCirc[cc]) { porCirc[cc] = [0, 0, 0, 0]; uitiCirc[cc] = 0; evCirc[cc] = 0; }
        porCirc[cc][g] += 1;
        uitiCirc[cc] += u[iv];
        evCirc[cc] += n[iv];
      }
    }
    // Los circuitos SIN eventos en la ventana no aparecen en idxPorGrupo, asi que no
    // existirian en porCirc. Se dan de alta en cero: un circuito sin eventos es
    // informacion -- esta sano -- y dejarlo fuera sesgaba los percentiles hacia arriba.
    // En la ventana completa son 24 de 208; en un rango de tres meses, 50 de 208, y ahi
    // el sesgo era grande: P50 daba 40 mirando solo los 158 con eventos contra 24
    // mirando los 208.
    CTX.circuitosNombres.forEach(function (c) {
      if (!porCirc[c]) { porCirc[c] = [0, 0, 0, 0]; uitiCirc[c] = 0; evCirc[c] = 0; }
    });
    var ALTO = CTX.grupos.length - 1;             // la clase mas critica es la ultima
    function totalDe(c) { var t = 0, k; for (k = 0; k < 4; k++) { t += porCirc[c][k]; } return t; }
    // Las DOS clases criticas, Medio-Alto (ALTO - 1) y Alto. Es la unica definicion de
    // "vano critico" del tablero, y la comparten el top 10 de aqui arriba y el ranking
    // de la fila de abajo. Vivia mas abajo, junto al ranking, y el top ordenaba por
    // `porCirc[c][ALTO]` a secas: dos paneles vecinos respondiendo la misma pregunta con
    // criterios distintos. MEDIDO sobre la ventana completa: de los diez circuitos del
    // top solo DOS estaban entre los diez ultimos del ranking. Ocho no. Uno al lado del
    // otro eso se lee como un error de datos.
    // El motivo de sumarlas es el que ya declaraba el panel de abajo: un circuito con
    // muchos vanos a un paso de la clase peor es tan accionable como uno que ya los
    // tiene ahi, y mirando solo Alto esa poblacion queda invisible.
    function critDe(c) { return porCirc[c][ALTO - 1] + porCirc[c][ALTO]; }
    // Desempate explicito por total de vanos y luego por nombre: sin el, dos circuitos
    // con los mismos vanos criticos podrian intercambiarse entre repintados segun el
    // orden en que Object.keys devuelva las llaves.
    var ranking = Object.keys(porCirc).sort(function (a, b) {
      return (critDe(b) - critDe(a)) || (totalDe(b) - totalDe(a)) ||
             (a < b ? -1 : 1);
    }).slice(0, 10);
    var nCircuitos = Object.keys(porCirc).length;
    // Plotly dibuja la primera categoria ABAJO: se invierte para que el #1 quede arriba.
    ranking.reverse();
    // Debajo de este ancho el numero no entra en el tramo. Plotly, cuando el texto
    // interior no cabe, lo mueve AFUERA de la barra -- y en una apilada eso lo deja
    // encima del tramo vecino. Se manda cadena vacia y el dato sigue en el hover.
    var MIN_PCT_TEXTO = 7;
    var topX = [], topY = [], topT = [], topL = [];
    for (g = 0; g < 4; g++) {
      var xs2 = [], ts2 = [], ls2 = [];
      for (i = 0; i < ranking.length; i++) {
        cc = porCirc[ranking[i]]; tot = totalDe(ranking[i]);
        var pct = tot ? 100 * cc[g] / tot : 0;
        xs2.push(pct);
        // Sin decimales: con tramos de ~20 px "42%%" entra y "42.3%%" no.
        ls2.push(pct >= MIN_PCT_TEXTO ? Math.round(pct) + '%%' : '');
        // La suma que ORDENA la lista va en el hover: sin ella el panel muestra
        // porcentajes de cuatro clases y el motivo del puesto se queda fuera.
        ts2.push('<b>' + ranking[i] + '</b><br>' + CTX.grupos[g] + ': ' + cc[g] +
                 ' de ' + tot + ' vanos (' + pct.toFixed(1) + '%%)' +
                 '<br>' + CTX.grupos[ALTO - 1] + ' + ' + CTX.grupos[ALTO] + ': ' +
                 critDe(ranking[i]) +
                 '<br>  ' + CTX.grupos[ALTO - 1] + ': ' + cc[ALTO - 1] +
                 '<br>  ' + CTX.grupos[ALTO] + ': ' + cc[ALTO]);
      }
      topX.push(xs2); topY.push(ranking.slice()); topT.push(ts2); topL.push(ls2);
    }
    Plotly.restyle(gd, {x: topX, y: topY, text: topL, hovertext: topT}, CTX.idx.barrasTop);

    // --- Fila 5: conteo de vanos en clase Alto por circuito -------------------------
    // Solo entran los circuitos con AL MENOS UNO. Con los demas incluidos los tres
    // cuartiles caen en cero (163 de 208 circuitos no tienen ninguno sobre esta base) y
    // el grafico deja de decir nada: una hilera de ceros y un puñado de barras al final.
    // El conteo, el orden y los cuartiles salen todos de `critDe` -- declarada arriba,
    // junto al top 10, porque ahora los DOS paneles ordenan por ella.
    // .slice() antes de ordenar: CTX.circuitosNombres es la paleta que resuelve circDe(),
    // y ordenarla en el sitio desalinearia todos los indices de CTX.circuitos.
    var conAlto = CTX.circuitosNombres.slice();
    conAlto.sort(function (a, b) { return (critDe(a) - critDe(b)) || (a < b ? -1 : 1); });
    var vals = conAlto.map(critDe);
    // Percentiles por interpolacion lineal, el metodo por defecto de numpy: asi lo que
    // marca la linea coincide con lo que daria el mismo calculo en Python.
    // Se usan P50, P75 y P95 -- no los cuartiles -- porque la distribucion tiene una cola
    // larga a la derecha: con 25/50/75 el ultimo grupo se llevaba un cuarto de los
    // circuitos y mezclaba los verdaderamente criticos con los del monton. Con este corte
    // el grupo de Riesgo Alto queda en el 3%% superior, que es lo accionable.
    // Los cuatro rangos se nombran por RIESGO en el titulo y en el hover: "P75" no le
    // dice nada a quien opera la red, y el numero del corte sigue disponible en el hover.
    var NOMBRE_RIESGO = ['Riesgo Bajo', 'Riesgo Medio', 'Riesgo Medio-Alto', 'Riesgo Alto'];
    // La hoja Circuitos del Excel lleva la banda sin el prefijo y en mayuscula sostenida.
    // El grafico conserva "Riesgo ..." porque ahi el prefijo es lo que distingue la banda
    // del circuito de los grupos de vano que colorean el resto del tablero.
    var NOMBRE_RANGO_EXCEL = ['BAJO', 'MEDIO', 'MEDIO-ALTO', 'ALTO'];

    function percentil(orden, q) {
      if (!orden.length) { return 0; }
      var h = (orden.length - 1) * q, lo = Math.floor(h), hi = Math.ceil(h);
      return orden[lo] + (orden[hi] - orden[lo]) * (h - lo);
    }
    var q1 = percentil(vals, 0.50), q2 = percentil(vals, 0.75), q3 = percentil(vals, 0.97);
    // Los cortes salen de interpolar, asi que caen en fracciones y arrastran ruido de
    // coma flotante: P90 se imprimia como 130.80000000000007. Se redondea SOLO para
    // mostrar; la comparacion de cada barra sigue usando el valor exacto.
    function fmtCorte(x) { return String(Math.round(x * 10) / 10); }
    var colsQ = [], hovQ = [], seg, vv, rangoPorCirc = {}, porRango = [0, 0, 0, 0];
    for (i = 0; i < conAlto.length; i++) {
      vv = vals[i];
      seg = vv <= q1 ? 0 : (vv <= q2 ? 1 : (vv <= q3 ? 2 : 3));
      // El NOMBRE, no el numero de banda: es lo que va a la hoja de circuitos del Excel.
      rangoPorCirc[conAlto[i]] = NOMBRE_RANGO_EXCEL[seg];
      porRango[seg] += 1;
      colsQ.push(CTX.coloresCuartil[seg]);
      // Los dos totales del circuito EN LA VENTANA ELEGIDA. Van en el hover y no
      // dibujados sobre la barra porque a 184 circuitos cada barra mide entre 2,8 px
      // (ventana de 1000) y 7,0 px (ventana de 2400): no hay donde poner un numero.
      // OJO con "eventos": es la suma de los eventos de cada vano del circuito, que es
      // la unidad de este tablero. NO es el conteo de fechas distintas que usa el
      // tablero de CIRCUITOS -- una misma salida golpea muchos vanos y ahi cuenta una
      // sola vez. Por eso la etiqueta lo dice explicitamente.
      hovQ.push('<b>' + conAlto[i] + '</b><br>' + CTX.grupos[ALTO - 1] + ' + ' +
                CTX.grupos[ALTO] + ': <b>' + vv + '</b>' +
                '<br>  ' + CTX.grupos[ALTO - 1] + ': ' + porCirc[conAlto[i]][ALTO - 1] +
                '<br>  ' + CTX.grupos[ALTO] + ': ' + porCirc[conAlto[i]][ALTO] +
                '<br>De ' + totalDe(conAlto[i]) + ' vanos del circuito' +
                '<br>UITI acumulado del circuito: <b>' +
                uitiCirc[conAlto[i]].toLocaleString(undefined,
                    {minimumFractionDigits: 1, maximumFractionDigits: 1}) + '</b>' +
                '<br>Eventos del circuito (suma por vano): <b>' +
                evCirc[conAlto[i]].toLocaleString() + '</b>' +
                '<br><b>' + NOMBRE_RIESGO[seg] + '</b>' +
                '<br>Cortes del ranking: P50=' + fmtCorte(q1) + ' P75=' + fmtCorte(q2) +
                ' P97=' + fmtCorte(q3));
    }
    // Las barras van en posiciones 0..n-1 y los nombres se ponen como ticks (ver el
    // comentario del eje): asi la division de cuartil puede caer en k - 0.5.
    var posQ = conAlto.map(function (_, k) { return k; });
    Plotly.restyle(gd, {x: [posQ], y: [vals], 'marker.color': [colsQ],
                        hovertext: [hovQ]}, [CTX.idx.altoCircuito]);
    // Las divisiones van ENTRE la ultima categoria de un cuartil y la primera del
    // siguiente: sobre un eje de categorias, k - 0.5 es justo esa frontera. Si un
    // cuartil queda vacio (muchos empates) no se dibuja su linea en vez de superponerla.
    // Dos conteos DISTINTOS, y los dos hacen falta en el titulo:
    //  - sin ningun evento en la ventana (el circuito no reporto nada);
    //  - en cero en la barra, que ademas de los anteriores incluye a los que si tuvieron
    //    eventos pero ninguno cayo en Medio-Alto ni en Alto.
    // Sobre la ventana completa el primero es 0 y el segundo 24: publicar solo el primero
    // dejaria 24 barras en cero sin explicacion aparente.
    var sinEventos = 0, enCero = 0;
    for (i = 0; i < conAlto.length; i++) {
      if (totalDe(conAlto[i]) === 0) { sinEventos += 1; }
      if (vals[i] === 0) { enCero += 1; }
    }

    var lqx = [], lqy = [], ymaxQ = (vals.length ? vals[vals.length - 1] : 1) * 1.08;
    [q1, q2, q3].forEach(function (q) {
      var k = 0;
      while (k < vals.length && vals[k] <= q) { k++; }
      if (k > 0 && k < vals.length) { lqx.push(k - 0.5, k - 0.5, null); lqy.push(0, ymaxQ, null); }
    });
    Plotly.restyle(gd, {x: [lqx], y: [lqy]}, [CTX.idx.cuartiles]);

    var gx = ejeGrilla(minX, maxX, CTX.resolucion, logx);
    var gy = ejeGrilla(minY, maxY, CTX.resolucion, logy);
    var z = [];
    for (var j = 0; j < gy.length; j++) {
      var fila = [];
      for (i = 0; i < gx.length; i++) { fila.push(grupoDe(gx[i], gy[j], geo)); }
      z.push(fila);
    }
    Plotly.restyle(gd, {z: [z], x: [gx], y: [gy]}, [CTX.idx.contorno]);

    var tx = logx ? 'log' : 'linear', ty = logy ? 'log' : 'linear';
    var cambios = {};
    // Cuantas muestras resume el reparto. Va por indice de anotacion, que es donde Plotly
    // guarda los titulos de subplot.
    var nMuestras = conteos[0] + conteos[1] + conteos[2] + conteos[3];
    ['barras', 'violinU'].forEach(function (k) {
      var par = CTX.titulos[k];
      cambios['annotations[' + par[0] + '].text'] = par[1] + ' (n = ' + nMuestras + ')';
    });
    // El titulo del top dice sobre cuantos circuitos se eligieron los 10: con un rango
    // corto pueden quedar menos de 10 circuitos con vanos, y el titulo lo tiene que decir.
    cambios['annotations[' + CTX.titulos.top[0] + '].text'] =
      CTX.titulos.top[1] + ' (' + ranking.length + ' de ' + nCircuitos + ')';
    // El titulo de la fila 5 dice cuantos circuitos entraron y sobre cuantos, porque el
    // grafico excluye a los que no tienen ningun vano en Alto.
    // El titulo dice los tres cortes y CUANTOS circuitos cae en cada rango, que es lo
    // que no se puede contar a ojo con 184 barras.
    cambios['annotations[' + CTX.titulos.altoCirc[0] + '].text'] =
      // Separador con guion simple: los titulos de subplot son anotaciones de Plotly y
      // no decodifican entidades HTML, asi que un &mdash; se imprimia tal cual.
      CTX.titulos.altoCirc[1] + ' (' + conAlto.length + ' circuitos)' +
      '<br><sup>' + NOMBRE_RIESGO.map(function (nom, k) {
        return nom + ': ' + porRango[k];
      }).join(' | ') +
      ' - Circuitos sin eventos: ' + sinEventos +
      ' | en cero (sin vanos Medio-Alto ni Alto): ' + enCero + '</sup>';
    cambios[CTX.ejes.altoY + '.range'] = [0, ymaxQ];
    cambios[CTX.ejes.altoX + '.range'] = [-0.7, conAlto.length - 0.3];
    CIRC_FILA5 = conAlto;
    cambios[CTX.ejes.mapaX + '.type'] = tx;
    cambios[CTX.ejes.mapaY + '.type'] = ty;
    cambios[CTX.ejes.violinUiti + '.type'] = ty;
    cambios[CTX.ejes.barras + '.range'] = [0, Math.max.apply(null, conteos) * 1.18];
    // Limites fijos tambien aqui; en log Plotly los espera ya en log10.
    cambios[CTX.ejes.mapaX + '.range'] = logx ? [Math.log10(minX * 0.85), Math.log10(maxX * 1.15)]
                                              : [0, maxX * 1.05];
    cambios[CTX.ejes.mapaY + '.range'] = logy ? [Math.log10(minY * 0.85), Math.log10(maxY * 1.15)]
                                              : [0, maxY * 1.05];
    Plotly.relayout(gd, cambios);
    // Va DESPUES del relayout de arriba: rotularFila5 lee el ancho ya aplicado.
    rotularFila5(gd);

    var total = conteos[0] + conteos[1] + conteos[2] + conteos[3];
    ESTADO = {n: n, u: u, idxPorGrupo: idxPorGrupo,
              // Lo que necesita la hoja de circuitos del Excel, ya calculado arriba para
              // el top 10 y para la fila de ranking: no se recorre nada dos veces.
              porCirc: porCirc, uitiCirc: uitiCirc, evCirc: evCirc,
              rangoPorCirc: rangoPorCirc,
              desde: CTX.meses[a] + '-01', hasta: CTX.finMes[b],
              nombre: 'etiquetas_vanos_' + CTX.meses[a] + '_' + CTX.meses[b] +
                      '_x' + (logx ? 'log' : 'lin') + '_y' + (logy ? 'log' : 'lin') +
                      '_' + prep + '.xlsx'};
    d.getElementById('va-aviso').textContent =
      'Rango efectivo: ' + CTX.meses[a] + ' a ' + CTX.meses[b] +
      ' (ajustado a meses completos). ' + total + ' de ' + CTX.vanos.length +
      // Sin el reparto por grupo: eran cuatro numeros sueltos, sin el nombre de su grupo,
      // justo encima del diagrama de barras que dibuja esos mismos cuatro conteos con su
      // nombre y a escala. Queda lo que el diagrama no puede decir: el rango efectivo y
      // cuantos vanos del total tuvieron eventos.
      ' vanos con eventos en el periodo.';
  }

  ['va-desde', 'va-hasta'].forEach(function (id) {
    var el = d.getElementById(id);
    if (el) { el.addEventListener('change', aplicar); }
  });
  var boton = d.getElementById('va-csv');
  if (boton) { boton.addEventListener('click', descargar); }
  aplicar();

  // Al redimensionar, Plotly reajusta la figura (config.responsive) pero no vuelve a
  // pasar por aplicar(), asi que las etiquetas de la fila 5 quedarian con el paso del
  // ancho anterior. Se re-rotula sola, con un respiro para no hacerlo en cada pixel.
  var _tRot = null;
  window.addEventListener('resize', function () {
    clearTimeout(_tRot);
    _tRot = setTimeout(function () { rotularFila5(d.getElementById(CTX.div)); }, 180);
  });
})();
</script>
''' % json.dumps(CONTEXTO_VANO, separators=(',', ':'))

    # include_plotlyjs=False: plotly.js ya viajo con el primer tablero, no hace falta repetirlo.
    FIGURA_VANO_HTML = pio.to_html(fig_vano, include_plotlyjs=False, full_html=False,
                                   div_id=DIV_VANO, default_width='100%',
                                   config={'responsive': True})

    # Panel arriba y figura debajo, igual que en la exportacion: el panel de este tablero son
    # dos fechas y un boton, y reservarle una columna del 30% dejaba el ancho muerto.
    PANEL_VANOS = PANEL_VANO_HTML + FIGURA_VANO_HTML + PANEL_VANO_JS

    def tabla_etiquetas_vano(desde=None, hasta=None, log_x=LOG_X, log_y=LOG_Y,
                             prep=PREPROCESO):
        """Etiqueta de cada vano para una configuracion, como DataFrame listo para CSV.

    Camino reproducible del boton del segundo tablero: mismo esquema y mismo orden.
    """
        etiquetas_mes = [str(m) for m in MESES]
        i = etiquetas_mes.index(desde) if desde else 0
        j = etiquetas_mes.index(hasta) if hasta else len(MESES) - 1
        if i > j:
            i, j = j, i

        n = N_MES[:, i:j + 1].sum(axis=1)
        u = U_MES[:, i:j + 1].sum(axis=1).round(4)
        con_eventos = (n > 0) & (u > 0)
        geo = GEOMETRIAS_VANO[str(ESPACIOS.index((log_x, log_y, prep)))]

        X = np.column_stack([n[con_eventos], u[con_eventos]]).astype(float)
        if log_x:
            X[:, 0] = np.log10(X[:, 0])
        if log_y:
            X[:, 1] = np.log10(X[:, 1])
        Z = (X - np.array(geo['offset'])) / np.array(geo['scale'])
        grupo = (((Z[:, None, :] - np.array(geo['centroides'])[None, :, :]) ** 2)
                 .sum(axis=2).argmin(axis=1))

        return (
            pd.DataFrame({
                'desde': str(MESES[i].to_timestamp().date()),
                'hasta': str(MESES[j].to_timestamp(how='end').date()),
                'vano': np.array(VANOS)[con_eventos],
                'circuito': np.array(CIRCUITO_DE_VANO)[con_eventos],
                'etiqueta': [NOMBRES_GRUPOS[g] for g in grupo],
                'num_eventos': n[con_eventos].astype(int),
                'uiti_acumulado': u[con_eventos],
            })
            .sort_values('uiti_acumulado', ascending=False)
            .reset_index(drop=True)
        )


    etiquetas_vano = tabla_etiquetas_vano()
    # El nombre sale de la propia tabla, igual que en `guardar_etiquetas` del primer
    # tablero. Antes traia '2025-11_2026-04_xlin_ylin_minmax' escrito a mano: si la base
    # cambia de periodo el archivo sigue diciendo el rango viejo, que es peor que no decirlo.
    _fila = etiquetas_vano.iloc[0]
    # El sufijo describe el espacio, y el espacio ahora es uno solo: el mismo del tablero.
    _espacio = (f'_x{"log" if LOG_X else "lin"}_y{"log" if LOG_Y else "lin"}_{PREPROCESO}')
    _destino = (REPO_ROOT / 'reports' / 'reportescircuitos' / 'artifacts' /
                f'etiquetas_vanos_{_fila["desde"][:7]}_{_fila["hasta"][:7]}'
                f'{_espacio}.csv')
    _destino.parent.mkdir(parents=True, exist_ok=True)
    etiquetas_vano.to_csv(_destino, index=False)
    print(f'{len(etiquetas_vano):,} vanos -> {_corta(_destino, REPO_ROOT)}')
    print(etiquetas_vano['etiqueta'].value_counts().reindex(NOMBRES_GRUPOS).to_string())
    etiquetas_vano.head()

    # --- Export web: SOLO el tablero de vanos ---------------------------------------------
    # En el cuaderno se muestran los DOS tableros (circuitos arriba, vanos abajo). Lo que se
    # abre en el navegador y lo que se publica como app en Databricks es solo el de VANOS: es
    # el que responde la pregunta operativa (que vanos y de que circuitos concentran la
    # criticidad), y el de circuitos queda como paso intermedio para leer dentro del cuaderno.
    #
    # Exportarlo SOLO obliga a dos cosas que no hacen falta cuando van juntos:
    #  1. `include_plotlyjs=True`. El PANEL_VANOS de la celda anterior se genero con False
    #     porque la libreria ya venia con el tablero de circuitos; sin ese acompanante hay que
    #     embeberla aqui o el documento no pinta nada.
    #  2. Anteponer PANEL_CSS. El bloque <style> de `.panel-agrup` vive en el panel de
    #     circuitos; el de vanos solo reusa la clase. Sin el, los controles salen sin estilos.
    import webbrowser

    DESTINO_PANEL = (Path(ruta_html) if ruta_html is not None
                     else REPO_ROOT / 'reports' / 'paneles' / '02_uiti_vano_kmeans.html')

    FIGURA_VANO_SOLA = pio.to_html(fig_vano, include_plotlyjs=True, full_html=False,
                                   div_id=DIV_VANO, default_width='100%',
                                   config={'responsive': True})
    # Panel arriba y figura a lo ancho debajo, al reves que los otros tres visores. Ahi el
    # reparto 30/70 gana porque sus paneles de control son largos; aqui el panel son DOS
    # fechas y un boton -- 212 px medidos contra 1.700 de figura --, asi que reservarle el 30%
    # del ancho dejaba unos 1.500 px muertos en la columna izquierda. Apilado, ese espacio se
    # lo queda la figura, que es la que tiene algo que dibujar.
    PANEL_VANOS_SOLO = PANEL_CSS + PANEL_VANO_HTML + FIGURA_VANO_SOLA + PANEL_VANO_JS


    def exportar_y_abrir(*, abrir=True):
        """Escribe el tablero de vanos en un documento autocontenido y lo abre en el navegador."""
        DESTINO_PANEL.parent.mkdir(parents=True, exist_ok=True)
        documento = f'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agrupamiento de vanos por UITI acumulado</title>
<style>
  html, body {{ margin: 0; padding: 12px; box-sizing: border-box;
                font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
                color: #2b2b2b; background: #fff; }}
  /* El div de la figura al 100%: es lo que hace que el tablero use el ancho de la
     pantalla. Va junto a `default_width` de to_html y a la ausencia de `width` en el
     layout -- si falta cualquiera de los tres, la figura colapsa al ancho por defecto. */
  #{DIV_VANO} {{ width: 100%; }}
</style>
</head>
<body>
{PANEL_VANOS_SOLO}
</body>
</html>
'''
        DESTINO_PANEL.write_text(documento, encoding='utf-8')
        mb = DESTINO_PANEL.stat().st_size / 1024 ** 2
        print(f'panel de vanos escrito en {_corta(DESTINO_PANEL, REPO_ROOT)} ({mb:,.1f} MB)')
        if abrir:
            webbrowser.open(DESTINO_PANEL.resolve().as_uri())
            print('abriendo en el navegador por defecto')
        else:
            print('ABRIR_EN_NAVEGADOR = False: no se abre nada, el archivo queda escrito')
        return DESTINO_PANEL


    RUTA_PANEL = exportar_y_abrir(abrir=ABRIR_EN_NAVEGADOR)

    return RUTA_PANEL
