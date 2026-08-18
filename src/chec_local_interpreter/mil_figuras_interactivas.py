"""Los tres paneles del informe que el tablero del 06 ya presenta vivos, en Plotly.

El informe los dibujaba en matplotlib y los embebia como PNG. Son los MISMOS tres --
el top de variables, el UITI medido contra el simulado y el grafo de relaciones -- y
tenerlos en dos librerias cuesta dos cosas concretas:

- quien lee el informe y despues abre el tablero ve dos dibujos distintos del mismo
  dato, y tiene que reconciliarlos de memoria;
- en el PNG se pierde el hover, que es justo donde vive lo que no cabe en la barra: el
  nombre completo de la variable, el valor al que hay que llevarla, y el desglose de
  cada UITI.

Las funciones PURAS se comparten con el tablero -- `plegar_rezagos`, `trazas_grafo`,
`rotacion_radial` -- para que la coincidencia no dependa de que nadie toque una de dos
copias. Lo que NO se comparte es la construccion de la figura: el tablero arma un
`make_subplots` de siete filas con `FigureWidget` y repinta por indice, y el informe
necesita tres figuras sueltas y estaticas en su HTML. Compartir eso obligaria a una de
las dos a cargar con la forma de la otra.

Se guardan como JSON de Plotly y no como PNG: es lo que deja la figura interactiva al
otro lado del limite `prepare()` -> `render()`, que son dos procesos distintos.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from chec_local_interpreter.mil_figuras import (
    COLOR_SIN_GRUPO,
    COLORES_GRUPOS,
    NOMBRES_GRUPOS,
    TOP_VARIABLES_PANEL,
    datos_grafo_radial,
)
from chec_local_interpreter.simulador_variables import rotacion_radial

# La rampa de posicion del ranking, igual que en el tablero: la primera barra opaca y
# las siguientes cada vez mas claras. El color NO codifica el grupo aqui -- todas las
# barras miden lo mismo -- y por eso no toca la paleta de criticidad.
COLOR_POSICION = [f"rgba(203,24,29,{0.95 - 0.055 * _p:.2f})"
                  for _p in range(TOP_VARIABLES_PANEL)]
# Verde cuando esa sola variable basta para caer al grupo Bajo. Mismo verde y mismo
# significado que el recuadro de mejora del mapa simulado, asi que no pide aprender un
# codigo nuevo.
COLOR_ALCANZA = "#1a9641"
# La trama de la barra simulada, la misma decision que ya se tomo en el informe y en el
# tablero: con el color puesto por el grupo, lo que separa medicion de prediccion es la
# trama, que ademas se ve en blanco y negro.
TRAMA_SIMULADO = "/"
COLOR_BORDE = "#5b4a48"
TAM_FUENTE = 9
#: Cuantos nodos del anillo se rotulan. El resto se dibuja igual -- el anillo es una
#: ESTRUCTURA y quitar nodos mentiria sobre ella -- pero sin texto: con sesenta y seis
#: nombres alrededor de un circulo de informe no se lee ninguno.
MAX_ROTULOS_GRAFO = 40


def _figura():
    import plotly.graph_objects as go

    return go.Figure()


def _disposicion(fig, *, alto: int, titulo_x: str = "", titulo_y: str = "") -> None:
    """El marco comun de los tres paneles.

    Sin titulo DENTRO de la figura: la seccion del informe ya rotula cada panel, y dos
    rotulos para un dibujo obligan al lector a decidir cual manda.
    """
    fig.update_layout(
        height=alto,
        margin=dict(l=10, r=10, t=24, b=10),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(size=TAM_FUENTE + 1, color="#2b2b2b"),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        hoverlabel=dict(font_size=TAM_FUENTE + 2),
    )
    if titulo_x:
        fig.update_xaxes(title_text=titulo_x)
    if titulo_y:
        fig.update_yaxes(title_text=titulo_y)


def _color_de_grupo(clase: Any) -> str:
    try:
        return COLORES_GRUPOS[int(clase)]
    except (TypeError, ValueError, IndexError):
        return COLOR_SIN_GRUPO


def _nombre_de_grupo(clase: Any) -> str:
    try:
        return NOMBRES_GRUPOS[int(clase)]
    except (TypeError, ValueError, IndexError):
        return "Sin grupo"


def figura_top_variables(relevancia: Mapping[str, Any] | None,
                         *, top: int = TOP_VARIABLES_PANEL):
    """El top de variables que bajan el UITI, una barra por par (variable, vano).

    Horizontal y no vertical: los nombres de las variables son largos -- "Riesgo por
    vegetación cercana al vano" -- y en vertical habria que girarlos o recortarlos.

    El hover lleva lo que la barra no puede: el codigo de columna, a que valor hay que
    llevar la variable, y si esa sola basta para caer al grupo Bajo.
    """
    vanos = (relevancia or {}).get("vanos") or {}
    filas: list[dict[str, Any]] = []
    for fid, entrada in vanos.items():
        for var in entrada.get("variables", []) or []:
            filas.append({**var, "fid": str(fid)})
    if not filas:
        return None

    filas.sort(key=lambda f: float(f.get("caida") or 0.0), reverse=True)
    filas = filas[: int(top)]
    # De menor a mayor: Plotly dibuja la primera categoria ABAJO, y el top se lee de
    # arriba hacia abajo.
    filas.reverse()

    import plotly.graph_objects as go

    etiquetas = [f"{f.get('label') or f['knob_id']} · vano {f['fid']}" for f in filas]
    colores = [
        COLOR_ALCANZA if f.get("alcanza") else COLOR_POSICION[min(i, len(COLOR_POSICION) - 1)]
        for i, f in enumerate(reversed(filas))
    ][::-1]
    hover = []
    for f in filas:
        valor = f.get("valor_optimo")
        valor_txt = (f"{valor:,.4g}" if isinstance(valor, (int, float))
                     else str(valor) if valor is not None else "sin valor")
        hover.append(
            f"<b>{f.get('label') or f['knob_id']}</b> ({f['knob_id']})"
            f"<br>Vano {f['fid']}"
            f"<br>Llevarla a <b>{valor_txt}</b>"
            f"<br>Caída: {float(f.get('caida') or 0.0):.2f} órdenes de magnitud"
            + ("<br><b>Sola alcanza el grupo Bajo</b>" if f.get("alcanza") else "")
        )

    fig = _figura()
    fig.add_trace(go.Bar(
        x=[float(f.get("caida") or 0.0) for f in filas],
        y=etiquetas,
        orientation="h",
        marker=dict(color=colores, line=dict(width=0.4, color=COLOR_BORDE)),
        hovertext=hover, hoverinfo="text", showlegend=False,
        text=[f["knob_id"] for f in filas], textposition="auto",
        insidetextfont=dict(size=TAM_FUENTE, color="white"),
        outsidetextfont=dict(size=TAM_FUENTE, color="#2b2b2b"),
    ))
    _disposicion(fig, alto=max(220, 26 * len(filas) + 90),
                 titulo_x="Caída alcanzable de UITI (órdenes de magnitud)")
    fig.update_yaxes(automargin=True, tickfont=dict(size=TAM_FUENTE))
    fig.update_xaxes(gridcolor="#e2e8f0", zeroline=False)
    return fig


def figura_uiti_medido_vs_simulado(simulacion: Mapping[str, Any] | None):
    """El UITI acumulado MEDIDO de cada vano contra el que predice la intervencion.

    La barra base es lo que dice la base de datos y no la base del modelo, igual que en
    el tablero: es el numero contra el que compara quien opera. La consecuencia hay que
    leerla con cuidado y por eso existe la barra de error: las dos barras son cantidades
    de NATURALEZA distinta, asi que su diferencia desnuda carga el error de nivel del
    modelo -- medido sobre 599 bolsas, correlaciona 0,950 pero su nivel corre +34%. El
    error de cada barra simulada es `|u_base - observado|`, el desfase del modelo en la
    BASE de ese mismo vano: lo unico local, medible y sin coste extra que hay.

    Sin `u_observado` se cae a la base del modelo y se DICE en el eje: es preferible a
    presentar como medicion algo que no lo es.
    """
    vanos = list((simulacion or {}).get("vanos") or [])
    if not vanos:
        return None

    import plotly.graph_objects as go

    hay_medido = all(v.get("u_observado") is not None for v in vanos)
    base = [float(v["u_observado"] if hay_medido else v["u_base"]) for v in vanos]
    simulado = [float(v["u_simulado"]) for v in vanos]
    error = [abs(float(v["u_base"]) - b) for v, b in zip(vanos, base)]
    fids = [str(v["fid"]) for v in vanos]

    hover_base, hover_sim = [], []
    for v, b, s, e in zip(vanos, base, simulado, error):
        hover_base.append(
            f"<b>Vano {v['fid']}</b>"
            f"<br>UITI {'medido' if hay_medido else 'base del modelo'}: {b:,.2f}"
            f"<br>Grupo: {_nombre_de_grupo(v.get('clase_base'))}")
        hover_sim.append(
            f"<b>Vano {v['fid']}</b>"
            f"<br>UITI simulado: {s:,.2f}"
            f"<br>Grupo: {_nombre_de_grupo(v.get('clase_simulada'))}"
            f"<br>Base del modelo: {float(v['u_base']):,.2f}"
            f"<br>Desfase del modelo en la base: {e:,.2f}")

    fig = _figura()
    fig.add_trace(go.Bar(
        x=fids, y=base, name="UITI medido (sólido)" if hay_medido
        else "UITI base del modelo (sólido)",
        marker=dict(color=[_color_de_grupo(v.get("clase_base")) for v in vanos],
                    line=dict(width=0.4, color=COLOR_BORDE)),
        hovertext=hover_base, hoverinfo="text",
    ))
    fig.add_trace(go.Bar(
        x=fids, y=simulado, name="UITI simulado (rayado)",
        marker=dict(color=[_color_de_grupo(v.get("clase_simulada")) for v in vanos],
                    line=dict(width=0.4, color=COLOR_BORDE),
                    pattern=dict(shape=TRAMA_SIMULADO, solidity=0.35,
                                 fgcolor=COLOR_BORDE)),
        error_y=dict(type="data", array=error, visible=True, color=COLOR_BORDE,
                     thickness=1.2, width=4),
        hovertext=hover_sim, hoverinfo="text",
    ))
    _disposicion(fig, alto=330, titulo_y="UITI acumulado")
    fig.update_xaxes(title_text="Vano", type="category",
                     tickfont=dict(size=TAM_FUENTE), tickangle=-45)
    fig.update_yaxes(rangemode="tozero", gridcolor="#e2e8f0")
    fig.update_layout(barmode="group", bargap=0.25)
    return fig


def figura_grafo_relaciones(grafo: Mapping[str, Any] | None,
                            features: Sequence[str] = ()):
    """El grafo del escenario como ANILLO, el mismo del panel del cuaderno 06.

    La disposicion sale de `datos_grafo_radial`, que a su vez usa `plegar_rezagos` y
    `trazas_grafo` -- las mismas dos piezas del tablero --, asi que el informe y el
    tablero dibujan literalmente el mismo anillo.

    Devuelve `(figura, motivo)`. El motivo viaja como texto porque un panel vacio se
    lee como "la intervencion no movio nada", que es lo contrario de "no hay vanos
    suficientes para reconstruir el grafo".
    """
    trazas, motivo = datos_grafo_radial(grafo, features)
    if trazas is None:
        return None, motivo

    import plotly.graph_objects as go

    pesos = list(trazas["pesos"]["peso"])
    maximo = max(pesos, default=0.0) or 1.0
    fig = _figura()

    # Una traza por arista y no una sola con `None` entre segmentos: el grosor y la
    # opacidad van ligados al peso RELATIVO de cada una, y en una traza unica el ancho
    # de linea es una propiedad de la traza entera.
    aristas_x = list(trazas["aristas"]["x"])
    aristas_y = list(trazas["aristas"]["y"])
    for k in range(0, len(aristas_x), 3):
        peso = pesos[k // 3] if k // 3 < len(pesos) else 0.0
        proporcion = peso / maximo
        fig.add_trace(go.Scatter(
            x=aristas_x[k:k + 2], y=aristas_y[k:k + 2], mode="lines",
            line=dict(color="#be185d", width=0.6 + 2.6 * proporcion),
            opacity=0.25 + 0.6 * proporcion,
            hoverinfo="skip", showlegend=False,
        ))

    nodos_x = list(trazas["nodos"]["x"])
    nodos_y = list(trazas["nodos"]["y"])
    textos = [str(t) for t in trazas["nodos"]["texto"]]
    fig.add_trace(go.Scatter(
        x=nodos_x, y=nodos_y, mode="markers",
        marker=dict(size=9, color="#0072b2",
                    line=dict(width=1.0, color="#ffffff")),
        hovertext=textos, hoverinfo="text", showlegend=False,
    ))

    # Los rotulos van como ANOTACIONES y no como `text` de la traza: un `Scatter` no
    # sabe girar su texto -- comprobado contra plotly 6.8.0, solo `Bar` y las
    # anotaciones llevan `textangle` -- y horizontales se enciman entre vecinos.
    for x, y, texto in list(zip(nodos_x, nodos_y, textos))[:MAX_ROTULOS_GRAFO]:
        angulo, anclaje = rotacion_radial(float(x), float(y))
        radio = math.hypot(float(x), float(y)) or 1.0
        fig.add_annotation(
            x=float(x) * (1.0 + 0.06 / radio), y=float(y) * (1.0 + 0.06 / radio),
            text=texto, showarrow=False, textangle=angulo, xanchor=anclaje,
            yanchor="middle", font=dict(size=TAM_FUENTE - 1, color="#334155"),
        )

    _disposicion(fig, alto=430)
    fig.update_xaxes(visible=False, range=[-1.55, 1.55])
    # `scaleanchor` para que el anillo sea un CIRCULO y no una elipse: sin el, el ancho
    # del contenedor decide la forma.
    fig.update_yaxes(visible=False, range=[-1.55, 1.55], scaleanchor="x", scaleratio=1)
    return fig, ""


#: La paleta de VANOS del tablero, copiada en el mismo orden. El color identifica al
#: VANO y no a su grupo, y los seis primeros son los del 01.4: un vano que era azul en
#: un cuaderno tiene que seguir siendo azul aqui.
COLORES_VANOS = ["#0072b2", "#009e73", "#cc79a7", "#56b4e9", "#e69f00", "#8c564b",
                 "#d55e00", "#6a3d9a", "#17becf", "#666666",
                 "#b2df8a", "#bcbd22", "#004949", "#920000", "#b39ddb"]
SERIE_TAM_UITI = 9
SERIE_TAM_EVENTOS = 8
#: El punto de la ventana de la que habla el panel, al triple. Igual que el punto de la
#: ventana vigente del tablero.
FACTOR_PUNTO_ACTIVO = 3


def _estilo_de_cupo(indice: int) -> tuple[str, str]:
    """Color y patron de linea del vano numero `indice`.

    La paleta se recorre en circulo y la SEGUNDA vuelta va discontinua: dos series del
    mismo color se separan igual por el patron de la linea, que es un canal que aqui
    estaba libre. Es preferible a inventar quince tonos mas que se confundirian de a
    pares -- eso serian dos series indistinguibles de verdad. Mismo recurso que el
    tablero.
    """
    color = COLORES_VANOS[indice % len(COLORES_VANOS)]
    return color, ("solid" if indice < len(COLORES_VANOS) else "dash")


def figura_series_por_ventana(
    series: Sequence[Mapping[str, Any]],
    *,
    ventana_activa: str | None = None,
    max_vanos: int = 10,
):
    """La serie de cada vano identificado a lo largo de TODAS las ventanas.

    Dice si el problema es cronico o aparecio el mes pasado, que se atiende distinto: un
    vano visto solo en la ventana en que salio critico no permite esa lectura.

    Tres decisiones copiadas del tablero, y cada una responde a algo:

    * **el color es del VANO**, no de su grupo -- aqui la pregunta es "cual de estos
      vanos", y el grupo lo lleva el relleno de cada punto;
    * **los eventos van en su PROPIO eje**, punteados y con marcador cuadrado. UITI y
      numero de eventos no comparten unidad, y en un solo eje el de escala grande
      aplasta al otro hasta dejarlo plano;
    * **el punto de `ventana_activa` va al triple**. Cada panel del informe habla de UNA
      ventana, y sin la marca hay que ir a buscarla en el eje.

    Las ventanas sin eventos van en CERO y no ausentes: una ventana tranquila de un vano
    critico es informacion, no un hueco.
    """
    series = [s for s in (series or []) if s.get("w")][: int(max_vanos)]
    if not series:
        return None

    from plotly.subplots import make_subplots

    import plotly.graph_objects as go

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for indice, serie in enumerate(series):
        color, trazo = _estilo_de_cupo(indice)
        ventanas = [str(w) for w in serie["w"]]
        uiti = [float(v) for v in serie.get("uv", [])]
        eventos = [float(v) for v in serie.get("n", [])]
        clases = list(serie.get("clase") or [])
        tamanos = [SERIE_TAM_UITI * (FACTOR_PUNTO_ACTIVO if w == ventana_activa else 1)
                   for w in ventanas]
        rellenos = [_color_de_grupo(clases[i]) if i < len(clases) else COLOR_SIN_GRUPO
                    for i in range(len(ventanas))]
        hover = [
            f"<b>Vano {serie['fid']}</b><br>Ventana {w}"
            f"<br>UITI acumulado: {u:,.2f}"
            f"<br>Eventos: {int(n) if i < len(eventos) else 0}"
            + (f"<br>Grupo: {_nombre_de_grupo(clases[i])}" if i < len(clases) else "")
            for i, (w, u, n) in enumerate(
                zip(ventanas, uiti, eventos + [0.0] * len(ventanas)))
        ]
        fig.add_trace(go.Scatter(
            x=ventanas, y=uiti, mode="lines+markers", name=f"vano {serie['fid']}",
            line=dict(color=color, width=2, dash=trazo),
            marker=dict(size=tamanos, color=rellenos,
                        line=dict(width=1.2, color=color)),
            hovertext=hover, hoverinfo="text", connectgaps=False,
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=ventanas, y=eventos, mode="lines+markers", name=f"eventos {serie['fid']}",
            line=dict(color=color, width=1.1, dash="dot"),
            marker=dict(size=[t * SERIE_TAM_EVENTOS / SERIE_TAM_UITI for t in tamanos],
                        symbol="square", color=rellenos,
                        line=dict(width=1.1, color=color)),
            hoverinfo="skip", showlegend=False, opacity=0.55,
        ), secondary_y=True)

    _disposicion(fig, alto=340)
    fig.update_xaxes(title_text="Ventana", type="category",
                     tickfont=dict(size=TAM_FUENTE))
    fig.update_yaxes(title_text="UITI acumulado", rangemode="tozero",
                     gridcolor="#e2e8f0", secondary_y=False)
    fig.update_yaxes(title_text="Eventos", rangemode="tozero", showgrid=False,
                     secondary_y=True)
    return fig


def _guardar(fig, destino: Path, nombre: str) -> str:
    destino.mkdir(parents=True, exist_ok=True)
    (destino / nombre).write_text(fig.to_json(), encoding="utf-8")
    return nombre


def figuras_interactivas_de_escenario(
    escenario: Mapping[str, Any],
    *,
    destino: str | Path,
    features: Sequence[str] = (),
    series: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Los tres paneles de un escenario, en JSON de Plotly y con ruta RELATIVA.

    JSON y no PNG porque `prepare()` y `render()` son dos procesos distintos y una
    figura interactiva no cruza ese limite como imagen. Relativa por lo mismo que los
    PNG: el sidecar deja de ser portable si la carpeta se copia con rutas absolutas.

    Cada panel se dibuja si tiene datos. Perder los tres porque falta uno dejaria al
    informe sin la parte que si existe.
    """
    destino = Path(destino)
    clave = str(escenario.get("ventana") or escenario.get("nombre", "escenario"))
    clave = "".join(c if c.isalnum() or c in "-_" else "_" for c in clave)

    top = figura_top_variables(escenario.get("relevancia") or {})
    uiti = figura_uiti_medido_vs_simulado(escenario.get("simulacion") or {})
    grafo, motivo = figura_grafo_relaciones(
        (escenario.get("simulacion") or {}).get("grafo_diferencia"), features)
    serie = figura_series_por_ventana(
        series, ventana_activa=str(escenario.get("ventana") or "") or None)

    return {
        "top_json": _guardar(top, destino, f"{clave}_top.json") if top else None,
        "uiti_json": _guardar(uiti, destino, f"{clave}_uiti.json") if uiti else None,
        "grafo_json": (_guardar(grafo, destino, f"{clave}_grafo.json")
                       if grafo else None),
        "serie_json": (_guardar(serie, destino, f"{clave}_serie.json")
                       if serie else None),
        "grafo_motivo": motivo,
    }
