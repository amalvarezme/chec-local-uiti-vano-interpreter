from __future__ import annotations

import html as _html_items
import os
import re as _re_items
import tempfile
from functools import lru_cache
from pathlib import Path

import pandas as pd

from chec_local_interpreter.agentes_linea_tiempo import (
    linea_desde_desglose,
    seccion_agentes_html,
)
from chec_local_interpreter.config import PROJECT_ROOT
from chec_local_interpreter.event_counts import count_unique_event_dates
from chec_local_interpreter.domain_context import NOMBRE_LEGIBLE_GRUPO
from chec_local_interpreter.ficha_circuito import (
    afectacion_html,
    ficha_general,
    tabla_clasificacion_html,
    tabla_ficha_html,
    tabla_ventanas_html,
    tipo_de_afectacion,
    vanos_de_mayor_impacto,
)
from chec_local_interpreter.glosario_variables import (
    nombrar_prosa_en_datos,
    nombre_con_codigo,
)
from chec_local_interpreter.vocabulario_informe import normalizar_vocabulario_en_datos
# La identidad visual que este informe COMPARTE con el gerencial. Se inyecta como
# valor en la f-string de abajo, asi que sus llaves van SIMPLES y no se vuelven a
# escanear; las reglas propias de esta plantilla siguen escribiendose dobles.
from chec_local_interpreter.informe_estilo import (
    CSS_IDENTIDAD,
    escudo_chec_html,
    pie_agentes_html,
)
import numpy as np
import plotly.graph_objects as go
import plotly.express as px


def plot_ranking_circuitos(raw_df, circuito_destacado, start_date=None, end_date=None):
    """El ranking de circuitos por vanos criticos, con la barra del circuito resaltada.

    Es la barra de apertura del informe, portada del segundo tablero del cuaderno 02.
    Sustituye a la nube de agrupamiento de circuitos, que situaba al circuito por TAMANO
    -- eventos contra UITI acumulado -- cuando la pregunta con la que se abre un informe
    de criticidad es en que puesto esta por vanos criticos y cuantos circuitos tiene por
    encima.

    El color de cada barra ES su banda de riesgo, asi que el circuito estudiado se marca
    con el BORDE y con una anotacion, nunca recoloreandolo: cambiarle el color mentiria
    sobre la banda en la que cae, que es justo el dato que la figura existe para dar.

    `circuito_destacado` admite un nombre (el informe por circuito) o una lista (el
    informe gerencial, que resalta los circuitos muestreados del grupo). Con varios se
    marcan todos los bordes pero no se anota ninguno: doce flechas sobre 208 barras de
    2,8 px tapan justo la figura que vienen a senalar.
    """
    from chec_local_interpreter.ranking_circuitos import (
        COLORES_RANGO,
        NOMBRES_RANGO,
        ranking_circuitos,
    )

    resultado = ranking_circuitos(raw_df, start_date, end_date)
    tabla = resultado.tabla
    if tabla.empty:
        return go.Figure()

    if circuito_destacado is None:
        destacados = []
    elif isinstance(circuito_destacado, str):
        destacados = [circuito_destacado] if circuito_destacado else []
    else:
        destacados = [str(c) for c in circuito_destacado if c]
    conjunto = set(destacados)
    posiciones = list(range(len(tabla)))
    valores = tabla["vanos_criticos"].tolist()
    es_destacado = [c in conjunto for c in tabla["circuito"]]

    hover = [
        f"<b>{fila.circuito}</b>"
        f"<br>Medio-Alto + Alto: <b>{fila.vanos_criticos}</b>"
        f"<br>  Medio-Alto: {fila.vanos_medio_alto}"
        f"<br>  Alto: {fila.vanos_alto}"
        f"<br>Vanos probables de causa de falla: {fila.vanos_con_eventos}"
        f"<br>UITI acumulado: <b>{fila.uiti_total:,.1f}</b>"
        # `eventos_total` suma los registros de CADA vano: la misma interrupcion
        # golpea muchos vanos, asi que este numero es siempre mayor que el de
        # interrupciones. Llamarlo "eventos" es lo que hacia leer 159.470 donde hay
        # 6.455 interrupciones sobre 27.390 vanos.
        f"<br>Registros vano-evento: <b>{fila.eventos_total:,}</b>"
        f"<br><b>{fila.rango}</b>"
        f"<br>Cortes: P50={resultado.cortes[0]:.1f} "
        f"P75={resultado.cortes[1]:.1f} P97={resultado.cortes[2]:.1f}"
        for fila in tabla.itertuples()
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=posiciones,
        y=valores,
        marker=dict(
            color=tabla["color"].tolist(),
            line=dict(
                width=[3.0 if d else 0.4 for d in es_destacado],
                color=["#0f172a" if d else "rgba(60,60,60,0.5)" for d in es_destacado],
            ),
        ),
        showlegend=False,
        cliponaxis=False,
        hovertext=hover,
        hovertemplate="%{hovertext}<extra></extra>",
    ))

    # Las tres divisiones en UNA sola traza, separadas por `None`. Caen en `k - 0.5`,
    # entre la ultima barra de una banda y la primera de la siguiente; por eso el eje es
    # lineal y no de categorias, donde Plotly leeria 11.5 como una categoria nueva y
    # pegaria las tres lineas al final del eje.
    tope = (max(valores) if valores else 1) * 1.08 or 1
    xs, ys = [], []
    for corte in resultado.cortes:
        k = 0
        while k < len(valores) and valores[k] <= corte:
            k += 1
        if 0 < k < len(valores):
            xs.extend([k - 0.5, k - 0.5, None])
            ys.extend([0, tope, None])
    if xs:
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", showlegend=False, hoverinfo="skip",
            line=dict(color="rgba(40,40,40,0.55)", width=1.2, dash="dot"),
        ))

    por_banda = tabla["rango"].value_counts()
    reparto = " | ".join(f"{nombre}: {int(por_banda.get(nombre, 0))}"
                         for nombre in NOMBRES_RANGO)
    if len(conjunto) > 1 and any(es_destacado):
        # Varios destacados: se dicen CUANTOS y de que banda, sin anotar ninguno.
        marcados = int(sum(es_destacado))
        encabezado = (
            f"Ranking de circuitos por vanos criticos — {marcados} circuitos "
            f"resaltados de {len(tabla)}"
        )
    elif any(es_destacado):
        destacado = destacados[0]
        fila = tabla[tabla["circuito"] == destacado].iloc[0]
        encabezado = (
            f"Ranking de circuitos por vanos criticos — {destacado}: "
            f"puesto {int(fila['posicion'])} de {len(tabla)} ({fila['rango']}, "
            f"{int(fila['vanos_criticos'])} vanos en Medio-Alto + Alto)"
        )
        indice = int(es_destacado.index(True))
        fig.add_annotation(
            x=indice, y=fila["vanos_criticos"], text=f"<b>{destacado}</b>",
            showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.6,
            arrowcolor="#0f172a", ax=0, ay=-38,
            font=dict(size=12, color="#0f172a"),
            bgcolor="rgba(255,255,255,0.85)", bordercolor="#0f172a", borderwidth=1,
        )
    else:
        encabezado = f"Ranking de circuitos por vanos criticos ({len(tabla)} circuitos)"

    periodo = (f"{start_date} a {end_date}" if start_date and end_date
               else "periodo completo")
    fig.update_layout(
        title=dict(
            text=(f"{encabezado}<br><sup>{reparto} — sin eventos: "
                  f"{resultado.circuitos_sin_eventos} | en cero (sin vanos Medio-Alto "
                  f"ni Alto): {resultado.circuitos_en_cero} — {periodo}</sup>"),
            font=dict(size=16, family="Arial, sans-serif"),
        ),
        # Nombres como ticks sobre un eje NUMERICO: ver el comentario de las divisiones.
        # Cada rotulo lleva delante su PUESTO, que es lo unico que permite saltar de
        # esta barra a la tabla de clasificacion: el orden de dibujo va de menos a mas
        # critico y el puesto va al reves, asi que la posicion en el eje no lo dice.
        xaxis=dict(
            type="linear",
            tickvals=posiciones,
            ticktext=[f"{int(p)}. {c}" for p, c in
                      zip(tabla["posicion"], tabla["circuito"])],
            tickangle=-90,
            tickfont=dict(size=8),
            title_text="Circuitos ordenados por vanos en Medio-Alto + Alto",
            range=[-0.7, len(tabla) - 0.3],
            showgrid=False,
            automargin=True,
        ),
        yaxis=dict(title_text="Vanos en Medio-Alto + Alto", rangemode="tozero",
                   gridcolor="#e2e8f0", griddash="dot"),
        plot_bgcolor="#f8fafc",
        paper_bgcolor="#ffffff",
        bargap=0.25,
        height=560,
        margin=dict(l=70, r=40, t=95, b=120),
        hovermode="closest",
    )
    return fig


def _norm_map_id(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .replace({"": pd.NA, "<NA>": pd.NA, "nan": pd.NA, "None": pd.NA})
    )


@lru_cache(maxsize=8)
def leer_geo_crudo(nombre_archivo: str):
    """El shapefile ENTERO, leido una sola vez por corrida.

    Medido en esta maquina: MVLINSEC 0,67 s y 37,1 MB, GDBCHEC_TRANSFOR 0,29 s y
    18,5 MB, SWITCHES 0,12 s y 7,3 MB. Sumados, 1,08 s y 62,9 MB por CADA mapa.

    Se leian enteros en cada llamada para despues quedarse con las filas de un solo
    circuito. Con tres mapas por informe eran 4,3 s; el deslizador que recorre las
    once ventanas del circuito los convertia en 13 s y doce veces esos 63 MB
    reservados y tirados, por leer doce veces exactamente los mismos bytes.

    Se cachea la lectura CRUDA y no el recorte por circuito. El recorte solo ayudaria
    si el mismo circuito se pidiera dos veces -- que es el caso del deslizador, si,
    pero por casualidad --, mientras que `/reporte-lote` recorre decenas de circuitos
    distintos y con el volveria a leer el disco entero en cada uno.

    Devuelve el marco COMPARTIDO. Los dos llamadores recortan con `.copy()` antes de
    escribir una sola columna; ver `test_el_marco_cacheado_no_se_puede_ensuciar_desde_
    un_llamador`.
    """
    geo_path = PROJECT_ROOT / "data" / "GEO" / nombre_archivo
    if not geo_path.exists():
        return None

    try:
        import geopandas as gpd
    except ImportError:
        return None

    return gpd.read_file(geo_path)


def _load_geo_vanos_for_circuit(circuito_name: str):
    lineas = leer_geo_crudo("MVLINSEC.shp")
    if lineas is None:
        return None

    required_cols = {"CIRCUITO", "G3E_FID", "geometry"}
    if not required_cols.issubset(lineas.columns):
        return None

    geo = lineas[lineas["CIRCUITO"].astype(str).eq(str(circuito_name))].copy()
    if geo.empty:
        return None

    geo["FID_VANO_GEO"] = _norm_map_id(geo["G3E_FID"])
    return geo


def _load_geo_points_for_circuit(circuito_name: str, filename: str, fid_column: str):
    points = leer_geo_crudo(filename)
    if points is None:
        return None

    required_cols = {"CIRCUITO", "G3E_FID", "geometry"}
    if not required_cols.issubset(points.columns):
        return None

    geo = points[points["CIRCUITO"].astype(str).eq(str(circuito_name))].copy()
    if geo.empty:
        return None
    if str(geo.crs) != "EPSG:4326":
        geo = geo.to_crs("EPSG:4326")
    geo[fid_column] = _norm_map_id(geo["G3E_FID"])
    geo = geo[geo.geometry.notna() & ~geo.geometry.is_empty].copy()
    return geo if not geo.empty else None


def _format_geo_value(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def _geo_points_for_folium(geo_points):
    if geo_points is None or geo_points.empty:
        return geo_points
    if str(geo_points.crs) != "EPSG:4326":
        geo_points = geo_points.to_crs("EPSG:4326")
    return geo_points[geo_points.geometry.notna() & ~geo_points.geometry.is_empty].copy()


def _folium_popup_html(row, fields: list[tuple[str, str]], title: str) -> str:
    items = []
    for column, label in fields:
        text = _format_geo_value(row.get(column, ""))
        if text:
            items.append(f"<tr><th style='text-align:left;padding-right:8px'>{label}</th><td>{text}</td></tr>")
    return f"<strong>{title}</strong><table>{''.join(items)}</table>"


def _add_folium_point_layer(fmap, geo_points, *, name: str, color: str, radius: int, fields: list[tuple[str, str]]) -> int:
    geo_points = _geo_points_for_folium(geo_points)
    if geo_points is None or geo_points.empty:
        return 0

    import folium

    group = folium.FeatureGroup(name=f"{name} ({len(geo_points)})", show=True)
    for _, row in geo_points.iterrows():
        geom = row.geometry
        folium.CircleMarker(
            location=[geom.y, geom.x],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            weight=1,
            tooltip=f"{name}: {_format_geo_value(row.get('CODIGO', row.get('G3E_FID', '')))}",
            popup=folium.Popup(_folium_popup_html(row, fields, name), max_width=420),
        ).add_to(group)
    group.add_to(fmap)
    return len(geo_points)


def _add_folium_equipment_legend(fmap) -> None:
    import folium

    legend_html = f"""
    <div style='position: fixed; bottom: 22px; right: 22px; z-index: 9999;
        background: rgba(255,255,255,.94); padding: 9px 11px; border: 1px solid #cbd5e1;
        border-radius: 6px; font: 12px Arial, sans-serif; line-height: 1.35; min-width: 190px;'>
      <strong>Equipos y capas</strong>
      <div><span style='display:inline-block;width:22px;height:0;border-top:4px solid #0ea5e9;margin-right:6px;vertical-align:middle;'></span>Vano / tramo MV</div>
      <div><span style='display:inline-block;width:22px;height:0;border-top:3px solid #9ca3af;margin-right:6px;vertical-align:middle;opacity:.75;'></span>Vano/tramo MV sin evento</div>
      <div><span style='display:inline-block;width:10px;height:10px;background:#f59e0b;border:1px solid #ffffff;border-radius:50%;margin-right:9px;'></span>Transformador</div>
      <div><span style='display:inline-block;width:10px;height:10px;background:#7c3aed;border:1px solid #ffffff;border-radius:50%;margin-right:9px;'></span>Interruptor / switch</div>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend_html))


# Los cuatro grupos del agrupamiento de vanos, con el semaforo de los cuadernos. Es el
# MISMO vocabulario que `ranking_circuitos.NOMBRES_GRUPOS_VANO` y que
# `mil_figuras.NOMBRES_GRUPOS`; aqui vive el color porque el mapa es quien lo pinta.
COLORES_CLASE_VANO: dict[str, str] = {
    "Bajo": "#1a9641",
    "Medio": "#f2c200",
    "Medio-Alto": "#ef6c00",
    "Alto": "#c62828",
}

# El vano que no tiene grupo en la ventana dibujada. `metric_by_vano` se calcula sobre
# el PERIODO y `metric_class_by_vano` sobre UNA ventana, y las bolsas salen de
# `ventanas_015.construir_tabla_vano_ventana`, que descarta las celdas con UITI cero:
# no tener grupo en la ventana equivale exactamente a no tener eventos en ella, y por
# eso el rotulo dice lo que le pasa al vano y no lo que le falta al dato.
#
# No es un quinto grupo -- es ausencia -- y por eso su color queda FUERA del semaforo.
ETIQUETA_SIN_EVENTOS = "Sin eventos"
COLOR_SIN_EVENTOS = "#94a3b8"


def plot_circuit_map_folium(
    df,
    circuito_name,
    date_range=None,
    color_target="number_of_events",
    metric_by_vano=None,
    metric_label: str | None = None,
    metric_column: str | None = None,
    metric_class_by_vano=None,
    metric_class_column: str | None = None,
    vanos_destacados=None,
):
    """Build the same layered GEO HTML map used in notebook 03, enriched with V3 metrics."""
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "chec_local_matplotlib"))
    import json as _json
    import folium
    import geopandas as gpd
    import matplotlib.colors as mcolors
    import matplotlib.cm as cm

    df_filtered = df[df["CIRCUITO"].astype(str).eq(str(circuito_name))].copy()
    if date_range is not None:
        df_filtered["FECHA_parsed"] = pd.to_datetime(df_filtered["FECHA"], errors="coerce")
        start_date = pd.to_datetime(date_range[0]) if date_range[0] else df_filtered["FECHA_parsed"].min()
        end_date = pd.to_datetime(date_range[1]) if date_range[1] else df_filtered["FECHA_parsed"].max()
        df_filtered = df_filtered[
            (df_filtered["FECHA_parsed"] >= start_date)
            & (df_filtered["FECHA_parsed"] <= end_date)
        ]
    else:
        start_date = pd.to_datetime(df_filtered["FECHA"], errors="coerce").min()
        end_date = pd.to_datetime(df_filtered["FECHA"], errors="coerce").max()

    geo_vanos = _load_geo_vanos_for_circuit(circuito_name)
    geo_trafos = _load_geo_points_for_circuit(circuito_name, "GDBCHEC_TRANSFOR.shp", "FID_TRAFO_GEO")
    geo_switches = _load_geo_points_for_circuit(circuito_name, "SWITCHES.shp", "FID_SWITCH_GEO")
    if geo_vanos is None and geo_trafos is None and geo_switches is None:
        raise ValueError(f"No hay geometria GEO para circuito {circuito_name}")

    if geo_vanos is not None and str(geo_vanos.crs) != "EPSG:4326":
        geo_vanos = geo_vanos.to_crs("EPSG:4326")

    if "FID_VANO" in df_filtered.columns:
        df_filtered["FID_VANO_NORM"] = _norm_map_id(df_filtered["FID_VANO"])
    else:
        df_filtered["FID_VANO_NORM"] = pd.NA
    if "UITI_VANO" in df_filtered.columns:
        df_filtered["UITI_VANO"] = pd.to_numeric(df_filtered["UITI_VANO"], errors="coerce").fillna(0)
    else:
        df_filtered["UITI_VANO"] = 0

    if metric_by_vano is not None:
        metric = pd.Series(metric_by_vano, dtype="float64").rename("metric_value")
        metric.index = _norm_map_id(pd.Series(metric.index, dtype="object"))
        metric_label = metric_label or "Métrica por vano"
        metric_column = metric_column or "metric_value"
    elif color_target == "number_of_events":
        metric = df_filtered.groupby("FID_VANO_NORM").size().rename("metric_value")
        metric_label = "Número de eventos"
        metric_column = "n_eventos"
    elif color_target in {"sum_uiti_vano", "UITI_VANO_sum"}:
        metric = df_filtered.groupby("FID_VANO_NORM")["UITI_VANO"].sum().rename("metric_value")
        metric_label = "Suma de UITI_VANO"
        metric_column = "uiti_vano_total"
    else:
        metric = df_filtered.groupby("FID_VANO_NORM").size().rename("metric_value")
        metric_label = "Número de eventos"
        metric_column = "n_eventos"

    if geo_vanos is not None:
        geo_plot = geo_vanos.merge(metric, left_on="FID_VANO_GEO", right_index=True, how="left")
        geo_plot["metric_value"] = pd.to_numeric(geo_plot["metric_value"], errors="coerce")
        geo_plot["has_v3_event"] = geo_plot["metric_value"].notna()
        geo_plot[metric_column] = geo_plot["metric_value"].fillna(0)
        if metric_class_by_vano is not None:
            class_metric = pd.Series(metric_class_by_vano, dtype="object").rename("metric_class")
            class_metric.index = _norm_map_id(pd.Series(class_metric.index, dtype="object"))
            metric_class_column = metric_class_column or "clase_riesgo"
            geo_plot = geo_plot.merge(class_metric, left_on="FID_VANO_GEO", right_index=True, how="left")
            geo_plot[metric_class_column] = geo_plot["metric_class"].fillna(ETIQUETA_SIN_EVENTOS)
    else:
        geo_plot = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    bounds_frames = []
    for gdf in [geo_plot, _geo_points_for_folium(geo_trafos), _geo_points_for_folium(geo_switches)]:
        if gdf is not None and not gdf.empty:
            bounds_frames.append(gdf[["geometry"]])
    if not bounds_frames:
        raise ValueError(f"No hay geometria utilizable para circuito {circuito_name}")
    bounds_source = pd.concat(bounds_frames, ignore_index=True)
    bounds = gpd.GeoDataFrame(bounds_source, geometry="geometry", crs="EPSG:4326").total_bounds
    center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]

    fmap = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron", width="100%", height="100%")

    colored_values = (
        geo_plot.loc[geo_plot["has_v3_event"], metric_column]
        if not geo_plot.empty and "has_v3_event" in geo_plot.columns
        else pd.Series(dtype=float)
    )
    if colored_values.empty:
        vmin, vmax_robust = 0, 1
    else:
        vmin = float(colored_values.min())
        vmax_robust = float(np.percentile(colored_values, 95))
        if vmax_robust <= vmin:
            vmax_robust = float(colored_values.max())
            if vmax_robust == vmin:
                vmax_robust = vmin + 1
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax_robust)
    mapper = cm.ScalarMappable(norm=norm, cmap=cm.turbo)
    # El semaforo de criticidad de los cuadernos: los CUATRO grupos que devuelve
    # `asignar_clase` (0=Bajo..3=Alto), los mismos que nombran el tablero de
    # agrupamiento, el ranking de circuitos y la prosa del informe. Ni uno mas: hasta
    # 2026-08-23 habia una quinta entrada, `Muy alto`, "por los caminos antiguos". Nada
    # en el repositorio la produce, pero la leyenda se construye recorriendo este mismo
    # diccionario, asi que salia dibujada en TODOS los mapas -- vacia y repitiendo el
    # rojo de `Alto`.
    class_colors = dict(COLORES_CLASE_VANO)

    # Los vanos a destacar, con el mismo normalizador de id que usa el resto del mapa:
    # `FID_VANO` llega con sufijo `.0` inconsistente y sin normalizar el conjunto no
    # coincide con NINGUNA geometria, asi que el destacado no se veria y nada fallaria.
    destacados = set()
    if vanos_destacados:
        destacados = set(_norm_map_id(pd.Series(list(vanos_destacados), dtype="object")))

    def style_line(feature):
        value = feature["properties"].get(metric_column)
        has_value = bool(feature["properties"].get("has_v3_event"))
        # Grosor y no color: el color ya significa el GRUPO de criticidad, y darle un
        # segundo significado dejaria el semaforo sin poder leerse.
        resaltado = str(feature["properties"].get("FID_VANO_GEO", "")) in destacados
        grosor = 8 if resaltado else 4
        if has_value:
            class_value = feature["properties"].get(metric_class_column) if metric_class_column else None
            if class_value in class_colors:
                return {"color": class_colors[class_value], "weight": grosor,
                        "opacity": 1.0 if resaltado else 0.88}
            if metric_class_column:
                # En modo grupo el color SIGNIFICA el grupo. El vano sin eventos en esta
                # ventana iba antes a la escala continua `turbo`, que pisa el semaforo:
                # medido, salia `#7a0402` -- un rojo mas oscuro que el `#c62828` de
                # `Alto` y a su lado en el mapa --, asi que se contaba como Alto sin
                # serlo.
                return {"color": COLOR_SIN_EVENTOS, "weight": grosor,
                        "opacity": 1.0 if resaltado else 0.7}
            rgba = mapper.to_rgba(min(float(value or 0), vmax_robust), bytes=True)
            return {"color": f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}", "weight": grosor,
                    "opacity": 1.0 if resaltado else 0.85}
        # Sin eventos en el periodo: la misma ausencia y por tanto el MISMO gris que el
        # vano sin eventos en esta ventana, con trazo fino porque aqui es red de fondo.
        # Con dos grises distintos la unica entrada "Sin eventos" de la leyenda rotulaba
        # uno y callaba el otro.
        return {"color": COLOR_SIN_EVENTOS, "weight": 2, "opacity": 0.45}

    if not geo_plot.empty:
        tooltip_fields = [col for col in ["FID_VANO_GEO", "CODIGO", "CIRCUITO", metric_column] if col in geo_plot.columns]
        if metric_class_column and metric_class_column in geo_plot.columns:
            tooltip_fields.append(metric_class_column)
        folium.GeoJson(
            geo_plot[[*tooltip_fields, "has_v3_event", "geometry"]],
            name=f"Vanos / tramos MV - {metric_label}",
            style_function=style_line,
            tooltip=folium.GeoJsonTooltip(fields=tooltip_fields),
        ).add_to(fmap)
        if metric_class_column:
            # Los cuatro grupos SIEMPRE -- la escala existe aunque este circuito no use
            # algun grupo en esta ventana --, y `Sin eventos` solo si de verdad hay algun
            # vano asi: anunciar un color que no esta en el mapa es el mismo error que
            # `Muy alto`, al reves.
            entradas = list(class_colors.items())
            con_evento = geo_plot["has_v3_event"]
            clases_dibujadas = (
                set(geo_plot.loc[con_evento, metric_class_column].dropna())
                if metric_class_column in geo_plot.columns
                else set()
            )
            # Hay gris en el mapa por DOS caminos, y los dos cuentan: el vano con
            # eventos en el periodo pero sin grupo en esta ventana, y el vano que no
            # tuvo eventos en todo el periodo. Mirar solo el primero dejaba mapas con
            # lineas grises que la leyenda no nombraba.
            hay_gris = bool(clases_dibujadas - set(class_colors)) or bool((~con_evento).any())
            if hay_gris:
                entradas.append((ETIQUETA_SIN_EVENTOS, COLOR_SIN_EVENTOS))
            legend_items = "".join(
                f"<div><span style='display:inline-block;width:11px;height:11px;background:{color};"
                f"margin-right:6px;border-radius:2px;'></span>{label}</div>"
                for label, color in entradas
            )
            legend_html = (
                "<div style='position: fixed; bottom: 22px; left: 50px; z-index: 9999; "
                "background: rgba(255,255,255,.94); padding: 8px 10px; border: 1px solid #cbd5e1; "
                "border-radius: 6px; font: 12px Arial, sans-serif;'>"
                "<strong>Clase</strong>"
                f"{legend_items}"
                "</div>"
            )
            fmap.get_root().html.add_child(folium.Element(legend_html))

    _add_folium_point_layer(
        fmap,
        geo_trafos,
        name="Transformadores",
        color="#f59e0b",
        radius=5,
        fields=[
            ("FID_TRAFO_GEO", "FID trafo"),
            ("CODIGO", "Código"),
            ("CIRCUITO", "Circuito"),
            ("CAPACIDAD_", "Capacidad"),
            ("FASES", "Fases"),
            ("MUNICIPIO", "Municipio"),
            ("DIRECCION", "Dirección"),
            ("ENERGIZADO", "Energizado"),
            ("EST_OPERAT", "Estado operativo"),
        ],
    )
    _add_folium_point_layer(
        fmap,
        geo_switches,
        name="Interruptores / switches",
        color="#7c3aed",
        radius=4,
        fields=[
            ("FID_SWITCH_GEO", "FID switch"),
            ("CODIGO", "Código"),
            ("TIPO", "Tipo"),
            ("ELEMENTO", "Elemento"),
            ("CIRCUITO", "Circuito"),
            ("CAPACIDAD_", "Capacidad"),
            ("FASES", "Fases"),
            ("MUNICIPIO", "Municipio"),
            ("DIRECCION", "Dirección"),
            ("ENERGIZADO", "Energizado"),
            ("EST_OPERAT", "Estado operativo"),
        ],
    )
    _add_folium_equipment_legend(fmap)
    leaflet_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
    fmap.fit_bounds(leaflet_bounds)
    map_name = fmap.get_name()
    bounds_json = _json.dumps(leaflet_bounds)
    render_fix = f"""
    <style>
      html, body, .folium-map {{
        width: 100% !important;
        height: 100vh !important;
        min-height: 520px !important;
        margin: 0 !important;
        padding: 0 !important;
      }}
    </style>
    <script>
      (function () {{
        var refitToCircuit = function () {{
          if (window.{map_name}) {{
            window.{map_name}.invalidateSize(true);
            window.{map_name}.fitBounds({bounds_json});
          }}
        }};
        window.addEventListener("load", function () {{
          setTimeout(refitToCircuit, 150);
        }});
        // This map is embedded via <iframe srcdoc="...">, and when that
        // iframe sits inside a `display:none` report tab, the container is
        // 0x0 at load time -- Leaflet's initial fitBounds() above computes
        // a bogus pan/zoom against that 0x0 size, so the map never actually
        // centers on the circuit until it is re-measured. The parent report
        // page dispatches a "resize" event on this window once the tab
        // holding this iframe actually becomes visible; re-run the same fit
        // then so the map re-centers on the studied circuit's zone.
        window.addEventListener("resize", refitToCircuit);
      }})();
    </script>
    """
    fmap.get_root().html.add_child(folium.Element(render_fix))
    return fmap


from plotly.subplots import make_subplots

def render_expert_alignment_tab(expert_alignment_validation_data):
    """
    Renderiza la segunda pestaña del reporte HTML con la comparación
    entre el agente de análisis histórico, el agente del modelo predictivo y reportes expertos.
    No devuelve JSON crudo; solo HTML escapado con las clases visuales del reporte.
    """
    import html

    analysis = expert_alignment_validation_data if isinstance(expert_alignment_validation_data, dict) else None

    def _clean_text(text) -> str:
        value = html.unescape("" if text is None else str(text))
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1].strip()
        return value

    def _escape(text):
        return html.escape(_clean_text(text), quote=False)

    def _value(value):
        source_labels = {
            "LLM1": "Agente Descriptor",
            "LLM2": "Agente predictivo",
            "LLM de datos históricos": "Agente Descriptor",
            "LLM del modelo predictivo": "Agente predictivo",
            "agente de análisis histórico": "Agente Descriptor",
            "Agente base": "Agente Descriptor",
            "agente del modelo predictivo": "Agente predictivo",
            "PDF_EXPERTO": "reportes expertos",
        }
        if isinstance(value, list):
            return ", ".join(_escape(source_labels.get(str(item), str(item))) for item in value if str(item).strip())
        return _escape(source_labels.get(str(value), value))

    def _empty_message():
        return "<p class='muted'>No hay elementos reportados para esta sección.</p>"

    def _finding_items(key, title):
        items = analysis.get(key, []) if analysis else []
        body = []
        if isinstance(items, list):
            for item in items:
                details = ""
                if isinstance(item, dict):
                    text = item.get("tema") or item.get("explicacion") or item.get("impacto_interpretativo") or ""
                    extra = item.get("explicacion") if item.get("tema") else ""
                    if text and extra and extra != text:
                        text = f"{text}: {extra}"
                    sources = item.get("fuentes")
                    if sources not in (None, "", []):
                        details = (
                            "<div class='item-details'>"
                            f"<span><strong>Fuentes:</strong> {_value(sources)}</span>"
                            "</div>"
                        )
                else:
                    text = str(item)
                if str(text).strip():
                    # Misma regla que en los demas items del informe: la primera letra
                    # en mayuscula, salvo que el item arranque con un codigo.
                    body.append(
                        f"<li>{_escape(_mayuscula_inicial(str(text)))}{details}</li>")
        content = f"<ul class='report-list'>{''.join(body)}</ul>" if body else _empty_message()
        return (
            "<div class='content-box'>"
            f"<h3 style='margin-top:0;'>{_escape(title)}</h3>"
            f"{content}"
            "</div>"
        )

    def _variables_table():
        rows = []
        items = analysis.get("variables_a_priorizar", []) if analysis else []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    "<tr>"
                    # `Nombre natural (CODIGO)`: el codigo solo no dice nada a quien lee
                    # el informe, y el nombre solo no se puede buscar en la tabla ni en
                    # el simulador. Esta columna es la que se lee para decidir donde
                    # intervenir, asi que necesita las dos mitades.
                    f"<td>{_escape(nombre_con_codigo(str(item.get('variable') or '')))}</td>"
                    f"<td>{_escape(item.get('prioridad'))}</td>"
                    f"<td>{_value(item.get('fuentes_que_la_respaldan'))}</td>"
                    f"<td>{_escape(item.get('justificacion'))}</td>"
                    f"<td>{_escape(item.get('tipo_de_validacion_sugerida'))}</td>"
                    "</tr>"
                )
        if not rows:
            return (
                "<div class='content-box'>"
                "<h3 style='margin-top:0;'>Variables a priorizar</h3>"
                f"{_empty_message()}"
                "</div>"
            )
        return (
            "<div class='content-box'>"
            "<h3 style='margin-top:0;'>Variables a priorizar</h3>"
            "<div class='table-scroll'><table class='compact-table'>"
            "<thead><tr><th>Variable</th><th>Prioridad</th><th>Fuentes</th>"
            "<th>Justificación</th><th>Validación sugerida</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            "</div>"
        )

    if not analysis:
        return (
            "<div class='summary-box'>"
            "<h2 style='margin-top:0;'>Comparación con reportes expertos</h2>"
            "<p>La comparación con reportes expertos no está disponible para esta ejecución.</p>"
            "</div>"
        )

    contexto = analysis.get("contexto", {}) if isinstance(analysis.get("contexto"), dict) else {}
    periodo = contexto.get("periodo", {}) if isinstance(contexto.get("periodo"), dict) else {}
    expert_rows = contexto.get("n_filas_expertas_comparadas")
    has_expert_rows = False
    try:
        has_expert_rows = int(expert_rows or 0) > 0
    except (TypeError, ValueError):
        has_expert_rows = bool(expert_rows)
    comparison_title = (
        "Comparación con reportes expertos"
        if has_expert_rows
        else "Comparación entre agentes disponibles"
    )
    comparison_scope = (
        "análisis histórico, modelo predictivo y reportes expertos"
        if has_expert_rows
        else "análisis histórico y modelo predictivo"
    )
    summary_bits = []
    if contexto.get("circuito"):
        summary_bits.append(f"<li><strong>Circuito:</strong> {_escape(contexto.get('circuito'))}</li>")
    if periodo.get("inicio") or periodo.get("fin"):
        summary_bits.append(
            f"<li><strong>Período:</strong> {_escape(periodo.get('inicio'))} a {_escape(periodo.get('fin'))}</li>"
        )
    if "n_filas_expertas_comparadas" in contexto:
        summary_bits.append(
            f"<li><strong>Filas expertas comparadas:</strong> {_escape(contexto.get('n_filas_expertas_comparadas'))}</li>"
        )
    if contexto.get("fuentes_usadas"):
        summary_bits.append(
            f"<li><strong>Fuentes usadas:</strong> {_value(contexto.get('fuentes_usadas'))}</li>"
        )
    if "modelo_experto_disponible" in contexto:
        disponibilidad = "Sí" if contexto.get("modelo_experto_disponible") else "No"
        summary_bits.append(f"<li><strong>Modelo Experto disponible:</strong> {_escape(disponibilidad)}</li>")
    if contexto.get("modelo_experto_razon"):
        summary_bits.append(
            f"<li><strong>Razón Modelo Experto:</strong> {_escape(contexto.get('modelo_experto_razon'))}</li>"
        )
    resumen = (
        "<ul class='report-list'>" + "".join(summary_bits) + "</ul>"
        if summary_bits else "<p class='muted'>No hay resumen contextual disponible.</p>"
    )

    synthesis = str(analysis.get("sintesis_final") or "").strip()
    synthesis_html = (
        "<div class='summary-box'>"
        "<h3 style='margin-top:0;'>Síntesis final</h3>"
        f"<ul class='report-list'><li>{_escape(_mayuscula_inicial(str(synthesis)))}</li></ul>"
        "</div>"
        if synthesis else
        "<div class='summary-box'><h3 style='margin-top:0;'>Síntesis final</h3><p class='muted'>No se entregó síntesis final.</p></div>"
    )

    return (
        f"<h2>{_escape(comparison_title)}</h2>"
        "<div class='summary-box'>"
        "<h3 style='margin-top:0;'>Resumen de la comparación</h3>"
        f"{resumen}"
        "</div>"
        + _finding_items(
            "coincidencias",
            f"Coincidencias entre {comparison_scope}",
        )
        + _finding_items(
            "diferencias",
            f"Diferencias entre {comparison_scope}",
        )
        + _variables_table()
        + synthesis_html
    )


def _format_elapsed_seconds(elapsed_seconds: float) -> str:
    """Format a wall-clock duration as `"Xm Ys"` (under an hour) or `"Xh Ym"`
    (an hour or more), e.g. `12m 33s` / `1h 5m`."""
    total_seconds = int(elapsed_seconds)
    if total_seconds < 0:
        total_seconds = 0
    if total_seconds >= 3600:
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m"
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"


_TOKEN_SOURCE_LABELS = {
    "measured": "medidos",
    "mixed": "medidos/estimados",
    "estimated": "aproximados",
}


def _token_source_label(token_source: str | None) -> tuple[str, str]:
    """Resolve a `token_source` value (`"measured"`/`"mixed"`/`"estimated"`,
    see `report_pipeline._resolve_token_usage`/`_resolve_stage_breakdown`)
    into its Spanish display label and its `"~"`-or-empty numeric prefix.

    Exact ("measured") counts drop the "~" prefix; anything with an
    estimated component keeps it, since it is still an approximation.
    Shared by the entrada/salida block, the whole-run total line, and the
    per-stage breakdown table below -- the same mapping used to be
    duplicated inline at each of those three call sites.
    """
    label = _TOKEN_SOURCE_LABELS.get(token_source, "aproximados")
    prefix = "" if token_source == "measured" else "~"
    return label, prefix


# --------------------------------------------------------------------------- items
# Los agentes entregan PROSA y el informe la presenta en items. Partirla y darle forma
# es trabajo de esta capa, no del modelo de lenguaje: pedirselo al agente lo deja a que
# se acuerde, y medido sobre 12 informes reales no se acordaba.

#: Un `_` o un digito delatan un CODIGO del dataset -- `uiti_acumulado`, `n_obs`, `NR_T` --.
#: Es la misma regla mecanica que usa `ortografia.py` para no acentuar nombres de columna,
#: y por el mismo motivo: capitalizarlos escribiria un identificador que no existe.
_ARRANQUE_DE_CODIGO = _re_items.compile(r"[_0-9]")


def _mayuscula_inicial(texto: str) -> str:
    """La primera letra de un item, en mayuscula. Un codigo se deja como esta.

    Solo actua cuando el primer caracter es una LETRA MINUSCULA. Un numero, una comilla
    angular o un signo de apertura se dejan intactos: ahi la mayuscula no va al principio
    y adivinar donde va es peor que no tocarlo.
    """
    if not texto or not texto[0].islower():
        return texto
    primera = texto.split(maxsplit=1)[0]
    if _ARRANQUE_DE_CODIGO.search(primera):
        return texto
    return texto[0].upper() + texto[1:]


def _texto_a_items(text: str, *, max_items: int | None = None) -> str:
    """Parte un parrafo en items de unas dos lineas.

    Corta en `.`, `!` y `?`, NUNCA en `;`: un punto y coma une dos clausulas de la misma
    idea, y cortar ahi dejaba trozos que empezaban por `y en los grupos...`. Medido: 99
    de 1.153 items terminaban en `;` antes de este cambio.
    """
    raw = ("" if text is None else str(text)).strip()
    if not raw:
        return ""
    frases = [s.strip() for s in _re_items.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    if not frases:
        frases = [raw]
    MAX_CHARS = 150  # ~2 lineas en un contenedor de 700 px
    items, actual, largo = [], [], 0
    for frase in frases:
        if actual and largo + len(frase) + 1 > MAX_CHARS:
            items.append(" ".join(actual))
            actual, largo = [frase], len(frase)
        else:
            actual.append(frase)
            largo += len(frase) + 1
    if actual:
        items.append(" ".join(actual))
    if max_items is not None:
        items = items[:max_items]
    return _envolver_items(items)


def _lista_a_items(items, *, max_items: int | None = None) -> str:
    """Los items que el agente ya entrego separados."""
    limpios = [str(item).strip() for item in (items or []) if str(item).strip()]
    if max_items is not None:
        limpios = limpios[:max_items]
    return _envolver_items(limpios)


def _envolver_items(items: list[str]) -> str:
    if not items:
        return ""
    lis = "".join(f"<li>{_escapar_html(_mayuscula_inicial(i))}</li>" for i in items)
    return f"<ul class='report-list'>{lis}</ul>"


def _escapar_html(texto: object) -> str:
    return _html_items.escape("" if texto is None else str(texto))


def _hipotesis_html(texto: str) -> str:
    """La hipotesis de causa: primera frase como parrafo, el resto en vinetas.

    Como lista entera, la primera frase -- que enuncia el marco del que cuelgan las
    demas -- se leia como una causa mas de la lista, al mismo nivel que las que la
    desarrollan. Es contexto, y se pinta como contexto.
    """
    raw = ("" if texto is None else str(texto)).strip()
    if not raw:
        return ""
    frases = [s.strip() for s in _re_items.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    if len(frases) < 2:
        return f"<p class='hipotesis-contexto'>{_escapar_html(_mayuscula_inicial(raw))}</p>"
    contexto = _escapar_html(_mayuscula_inicial(frases[0]))
    return (f"<p class='hipotesis-contexto'>{contexto}</p>"
            + _texto_a_items(" ".join(frases[1:])))


def render_llm_analysis(
    validation_data: dict,
    raw_df: pd.DataFrame,
    selected_circuitos: list[str],
    start_date: str = None,
    end_date: str = None,
    output_dir: str | Path = PROJECT_ROOT / "reports" / "reportescircuitos" / "html",
    output_filename: str | None = None,
    llm_model: str = "Desconocido",
    llm_provider: str = "Desconocido",
    tokens_input: int | None = None,
    tokens_output: int | None = None,
    tokens_total: int | None = None,
    token_source: str = "estimated",
    token_total_source: str | None = None,
    elapsed_seconds: float | None = None,
    stage_breakdown: list[dict] | None = None,
    all_circuits_df: pd.DataFrame | None = None,
    inference_results: dict | None = None,
    inference_analysis: dict | None = None,
    expert_alignment_analysis: dict | None = None,
    expert_alignment_matches: list[dict] | None = None,
    # Una lista: un mapa por ventana estudiada. Un `dict` suelto es la forma anterior
    # -- una sola ventana con su par base/simulado -- y se sigue aceptando para que una
    # corrida ya guardada en disco se vuelva a renderizar sin perder la seccion.
    mapas_ventana: list[dict] | dict | None = None,
):
    """
    Renders the structured JSON output from the LLM into a beautiful HTML format
    suitable for Jupyter Notebooks, incorporating interactive Plotly charts.
    """
    from IPython.display import display, Markdown, HTML
    from datetime import datetime
    import os

    validation_data = validation_data or {}

    # La PROSA de los tres agentes, con cada codigo nombrado la primera vez que aparece.
    # Se hace aqui, al pintar, y no al guardar: el `.out.json` es el artefacto que el
    # propio `validate` del agente acepto, y reescribirlo lo separaria de su validacion.
    # Las claves de identidad (`variable`, `data_ref`, ...) quedan intactas -- ver
    # `glosario_variables.CLAVES_DE_IDENTIDAD`.
    # Y el VOCABULARIO del informe unificado en la misma pasada: "circuitos de la
    # flota" pasa a "circuitos totales" y "ventana pico" a "ventana de mayor aporte
    # UITI", que era lo que la revision pedia. Al hacerse al pintar, las corridas ya
    # archivadas se vuelven a dibujar con el vocabulario nuevo sin gastar un token.
    def _prosa(datos):
        return normalizar_vocabulario_en_datos(nombrar_prosa_en_datos(datos))

    validation_data = _prosa(validation_data)
    inference_analysis = _prosa(inference_analysis) if inference_analysis else inference_analysis
    expert_alignment_analysis = (
        _prosa(expert_alignment_analysis) if expert_alignment_analysis
        else expert_alignment_analysis
    )

    # El ranking del cuaderno 02 compara este circuito contra la flota entera, asi que
    # necesita el dataframe multi-circuito (`all_circuits_df`), no `raw_df`, que el que
    # llama ya filtro al circuito. Sin el se degrada a un ranking de un solo circuito, que
    # es inutil pero no revienta.
    fig_ranking = plot_ranking_circuitos(
        all_circuits_df if all_circuits_df is not None else raw_df,
        selected_circuitos[0] if selected_circuitos else "",
        start_date,
        end_date,
    )

    primary_circuit = selected_circuitos[0] if selected_circuitos else "TODOS"

    # `plotly.js` UNA vez y por su cuenta, no colgando de la figura del ranking. Todas
    # las demas se embeben con `include_plotlyjs=False`, asi que mientras esto viajaba
    # dentro del ranking, un informe sin ranking dejaba MUDAS a las otras: los paneles
    # interactivos del MIL se montaban en un `<div>` sin biblioteca que los dibujara, y
    # eso no da error, da un hueco en blanco.
    html_plotlyjs = (
        "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js' charset='utf-8'></script>")
    html_clusters = fig_ranking.to_html(full_html=False, include_plotlyjs=False) if fig_ranking else ""

    def _escape(text):
        import html
        return html.escape("" if text is None else str(text))

    def _iframe_srcdoc(html: str, *, height: int = 620) -> str:
        if not html:
            return ""
        return (
            f"<iframe class='embedded-map-frame' srcdoc=\"{_escape(html)}\" "
            f"loading='lazy' style='width:100%;height:{height}px;border:0;background:#ffffff;'></iframe>"
        )

    # `_texto_a_items` y `_lista_a_items` viven a nivel de modulo (ver arriba): eran
    # closures y no habia forma de probarlas sin renderizar un informe entero.
    _text_to_items = _texto_a_items
    _list_to_items = _lista_a_items

    def _figure_html(fig, title=None, show_title=False):
        if not fig:
            return ""
        if isinstance(fig, (str, Path)) and str(fig).endswith(".json"):
            # Los tres paneles que el tablero del 06 presenta vivos viajan como JSON de
            # Plotly: `prepare()` y `render()` son dos procesos, y una figura
            # interactiva no cruza ese limite como imagen. Se rehidrata y se embebe
            # INTERACTIVA, con su hover -- que es donde vive el nombre completo de cada
            # variable y el desglose de cada barra.
            #
            # Un JSON ilegible cae al mismo aviso que cualquier otro fallo de figura, y
            # nunca tumba el informe: el panel se pierde, la corrida no.
            try:
                import plotly.io as pio

                ruta_json = Path(fig)
                if not ruta_json.exists():
                    raise FileNotFoundError(f"Figura no encontrada: {ruta_json}")
                figura = pio.from_json(ruta_json.read_text(encoding="utf-8"))
                if show_title and title:
                    figura.update_layout(title=dict(text=title, font=dict(size=14)))
                return figura.to_html(full_html=False, include_plotlyjs=False)
            except Exception as exc:
                return f"<p class='muted'>No se pudo renderizar la figura: {_escape(exc)}</p>"
        if isinstance(fig, (str, Path)):
            # `_run_inference_simulator` (task 3.2) persists figures as PNG
            # files under run_dir rather than passing live matplotlib Figure
            # objects across the prepare()/render() process boundary --
            # `render()` (task 3.4) only ever has a path here. Base64-embed
            # it the same way a live figure would be embedded below; a
            # missing/unreadable file falls through to the same fallback
            # message as any other rendering failure, never a crash.
            try:
                import base64

                png_path = Path(fig)
                if not png_path.exists():
                    raise FileNotFoundError(f"Figura no encontrada: {png_path}")
                encoded = base64.b64encode(png_path.read_bytes()).decode("ascii")
                alt = _escape(title or "Grafica")
                return f"<img class='embedded-figure' src='data:image/png;base64,{encoded}' alt='{alt}'>"
            except Exception as exc:
                return f"<p class='muted'>No se pudo renderizar la figura: {_escape(exc)}</p>"
        if hasattr(fig, "to_html"):
            try:
                import plotly.graph_objects as go
                fig_copy = go.Figure(fig)
                if show_title and title:
                    fig_copy.update_layout(title=dict(text=title, font=dict(size=14)))
                else:
                    fig_copy.update_layout(title=dict(text=""), margin=dict(t=20))
                return fig_copy.to_html(full_html=False, include_plotlyjs=False)
            except Exception:
                return fig.to_html(full_html=False, include_plotlyjs=False)
        try:
            import base64
            from io import BytesIO

            buffer = BytesIO()
            fig.savefig(buffer, format="png", bbox_inches="tight", dpi=140)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            alt = _escape(title or "Grafica")
            return f"<img class='embedded-figure' src='data:image/png;base64,{encoded}' alt='{alt}'>"
        except Exception as exc:
            return f"<p class='muted'>No se pudo renderizar la figura: {_escape(exc)}</p>"

    def _chart_panel(title, html):
        if not html:
            return ""
        return f"<div class='chart-panel'><h3>{_escape(title)}</h3>{html}</div>"

    def _mapas_ventana_html() -> str:
        """Un mapa por cada ventana del circuito: en que estado esta cada vano.

        Cada mapa describe UNA ventana. Un mapa del periodo entero superpone seis meses
        de estados que se atienden distinto, y sobre el no se puede decidir nada.

        Aqui se dibujaba el par base/simulado de una sola ventana: el estado actual y
        el estado tras el plan. Ese par respondia "que cambia si va la cuadrilla", que
        es exactamente lo que la tabla del plan ya da con numeros -- y con el delta de
        grupo por vano --, asi que el mapa simulado repetia en forma de mapa una
        respuesta que el informe ya tenia. La secuencia de ventanas dice algo que
        ninguna tabla dice de un vistazo: DONDE esta el problema en el trazado y como
        se movio de una ventana a la siguiente.

        Son TODAS las ventanas y no solo las tres estudiadas. Estudiar tres recorta la
        parte cara -- relevancia, diagnostico y simulacion --, y el mapa no es esa
        parte. Las tres estudiadas se marcan: son las unicas con escenario detras, y sin
        la marca las once posiciones se leen como equivalentes.

        La clase de cada vano sale del u-hat del modelo sobre la geometria del 01.4,
        para que el mapa este en la misma escala que el diagnostico y que la tabla.
        """
        if primary_circuit == "TODOS":
            return ""
        # Una sola ventana en forma de dict es la forma ANTERIOR del sidecar: una
        # corrida vieja se sigue renderizando en vez de perder la seccion entera.
        ventanas = ([mapas_ventana] if isinstance(mapas_ventana, dict)
                    else list(mapas_ventana or []))
        ventanas = [v for v in ventanas
                    if isinstance(v, dict) and (v.get("base") or {}).get("valor")]
        if not ventanas:
            return ""

        capas = []
        etiquetas = []
        fallos = []
        for mapa in ventanas:
            base = mapa.get("base") or {}
            etiqueta = _escape(mapa.get("ventana") or "")
            periodo = _escape(mapa.get("periodo") or "")
            destacados = {str(f) for f in (mapa.get("top_uiti") or [])}
            try:
                dibujado = plot_circuit_map_folium(
                    raw_df,
                    primary_circuit,
                    date_range=(start_date, end_date) if start_date or end_date else None,
                    metric_by_vano=pd.Series(base.get("valor") or {}, dtype="float64"),
                    metric_label="Grupo de criticidad observado",
                    metric_column="grupo_base",
                    metric_class_by_vano=pd.Series(base.get("clase") or {}, dtype="object"),
                    metric_class_column="clase",
                    vanos_destacados=destacados,
                )
            except Exception as exc:
                # Una ventana que no se puede dibujar no puede llevarse las otras dos.
                fallos.append(f"{etiqueta}: {_escape(exc)}")
                continue
            # Solo tres de las once ventanas tienen escenario, diagnostico y plan
            # detras. Sin decirlo, las once posiciones del deslizador se leen como
            # equivalentes y quien busque en el informe el escenario de la ventana que
            # esta viendo no lo encuentra en ocho de los once casos.
            estudiada = bool(mapa.get("estudiada"))
            etiquetas.append((etiqueta, estudiada))
            activa = " activa" if not capas else ""
            nota_estudiada = (
                " &middot; <b>con diagnóstico y plan en este informe</b>"
                if estudiada else "")
            capas.append(
                f"<div class='mapa-ventana{activa}' data-indice='{len(capas)}'>"
                f"<p class='muted' style='margin:0 0 6px 0;'>Ventana <b>{etiqueta}</b>"
                f"{f' &mdash; {periodo}' if periodo else ''} &middot; "
                f"{len(destacados)} vanos de mayor UITI acumulado resaltados"
                f"{nota_estudiada}</p>"
                f"{_iframe_srcdoc(dibujado.get_root().render(), height=380)}</div>"
            )

        if not capas:
            return (f"<p class='muted'>No se pudieron renderizar los mapas por ventana: "
                    f"{'; '.join(fallos)}</p>")

        # UN visor. Tres mapas apilados obligan a bajar y subir para compararlos, y a esa
        # distancia la comparacion se hace de memoria; en el mismo sitio, uno encima del
        # otro, el cambio entre ventanas se ve como un movimiento.
        #
        # El deslizador solo aparece cuando hay mas de una ventana: un control de una
        # sola posicion no hace nada y se lee como que algo se rompio.
        #
        # El deslizador va FLANQUEADO por dos flechas. Saltar de V6 a V7 arrastrando un
        # control de once posiciones sobre 300 px pide una punteria que no hace falta
        # pedir: la pregunta habitual es "y la siguiente", y eso es un clic.
        control = ""
        if len(capas) > 1:
            marcas = "".join(
                f"<span class='marca-estudiada' style='flex:1;text-align:center;'>{e}</span>"
                if estudiada else
                f"<span style='flex:1;text-align:center;'>{e}</span>"
                for e, estudiada in etiquetas)
            control = (
                "<div class='mapa-control'>"
                "<div class='mapa-fila-control'>"
                "<button type='button' class='mapa-flecha mapa-anterior' "
                "aria-label='Ventana anterior'>&#9664;</button>"
                f"<input type='range' min='0' max='{len(capas) - 1}' value='0' step='1' "
                "class='mapa-deslizador' aria-label='Ventana del mapa'>"
                "<button type='button' class='mapa-flecha mapa-siguiente' "
                "aria-label='Ventana siguiente'>&#9654;</button>"
                "</div>"
                f"<div class='mapa-marcas'>{marcas}</div>"
                "</div>"
            )

        aviso = (f"<p class='muted'>Sin mapa: {'; '.join(fallos)}</p>" if fallos else "")
        nota = (
            "<div class='summary-box'>"
            "<h3 style='margin-top:0;'>Cómo leer el mapa</h3>"
            "<ul class='report-list'>"
            "<li>Es un solo mapa: el deslizador recorre <b>todas</b> las ventanas del "
            "circuito en orden de tiempo, y la última es cómo está hoy.</li>"
            "<li>Las ventanas <b>en azul y negrita</b> son las tres que este informe "
            "estudia a fondo: son las únicas con diagnóstico, plan y escenario. Las "
            "demás muestran el estado del circuito, sin análisis detrás.</li>"
            "<li>El color de cada vano es su grupo de criticidad en esa ventana, el "
            "mismo que usa el diagnóstico.</li>"
            "<li>Los trazos <b>gruesos</b> son los quince vanos de mayor UITI acumulado "
            "de esa ventana. El color dice en qué grupo está un vano; el grosor, cuáles "
            "concentran el impacto — que no siempre son los mismos.</li>"
            "<li>Se dibujan TODOS los vanos de la ventana, no solo los del diagnóstico: "
            "un vano sin marcar es un vano que no necesita obra, no un vano sin datos.</li>"
            "<li>Moviendo el deslizador se ve si el problema se queda en el mismo tramo "
            "o se mueve por el circuito.</li>"
            "</ul></div>"
        )
        # El mapa se dibuja mas bajo que antes (380 px contra 560) y con un boton de
        # pantalla completa. A 560 px empujaba media pantalla de informe hacia abajo en
        # cada scroll, y cuando de verdad hace falta mirar el trazado -- localizar un
        # vano concreto -- 560 px tampoco alcanzaban: la respuesta no era un tamano
        # intermedio, era poder elegir.
        return (f"<h3>Estado del circuito en las ventanas estudiadas</h3>"
                f"<div class='visor-mapas'>"
                f"<div class='mapa-barra'>"
                f"<button type='button' class='mapa-pantalla-completa'>"
                f"⤢ Ampliar a pantalla completa</button></div>"
                f"{control}{''.join(capas)}</div>"
                f"{aviso}{nota}")

    def _orden_ventana(etiqueta):
        resto = str(etiqueta).lstrip("Vv")
        return (int(resto), "") if resto.isdigit() else (10**9, str(etiqueta))

    def _tabla_variables(bloque, titulo, nota):
        """El ranking de un grupo de variables, como tabla legible.

        Manda `n_vanos_alcanza`: en cuantos vanos ESA SOLA variable basta para caer al
        grupo mas bajo. Ordenar por caida de UITI responde a "que baja más el número",
        que no es la pregunta -- una variable que baja mucho sin cruzar ninguna frontera
        de grupo no cambia ninguna decision.
        """
        filas = [f for f in (bloque or []) if isinstance(f, dict)][:8]
        if not filas:
            return ""
        celdas = []
        for fila in filas:
            avance = fila.get("avance_mediano")
            avance_txt = "N/D" if avance is None else f"{100 * float(avance):.0f}%"
            valor = fila.get("valor_tipico")
            valor_txt = "N/D" if valor is None else (
                f"{valor:g}" if isinstance(valor, (int, float)) else str(valor))
            celdas.append(
                "<tr>"
                # El codigo del knob ES el nombre de la columna del dataset, asi que el
                # glosario lo resuelve. `label` solo se usa cuando no hay codigo: viene
                # del catalogo de controles y suele ser el codigo otra vez.
                f"<td style='text-align:left;'>"
                f"{_escape(nombre_con_codigo(str(fila.get('knob_id'))) if fila.get('knob_id') else (fila.get('label') or ''))}</td>"
                f"<td>{_escape(valor_txt)}</td>"
                f"<td>{int(fila.get('n_vanos_alcanza') or 0)} / {int(fila.get('n_vanos') or 0)}</td>"
                f"<td>{avance_txt}</td>"
                "</tr>"
            )
        # `compact-table`, la MISMA de "Variables a priorizar". Antes era
        # `report-table`, una clase que el informe usa en dos sitios y no declara en
        # ninguno: cero reglas CSS, asi que estas tablas salian sin una sola division
        # de fila ni de columna mientras su vecina si las tenia.
        return (
            f"<h4>{_escape(titulo)}</h4>"
            f"<p class='muted' style='margin-top:-6px;'>{_escape(nota)}</p>"
            "<div class='table-scroll'><table class='compact-table'>"
            "<thead><tr><th>Variable</th><th>Valor que consigue el mínimo</th>"
            "<th>Vanos que alcanzan Bajo</th><th>Avance mediano hacia Bajo</th></tr></thead>"
            f"<tbody>{''.join(celdas)}</tbody></table></div>"
        )

    def _tabla_simulacion(simulacion):
        """Que le pasa al UITI y al grupo de cada vano identificado si se interviene."""
        vanos = [v for v in ((simulacion or {}).get("vanos") or []) if isinstance(v, dict)]
        if not vanos:
            return ""
        # Los nombres NO se reescriben aqui: son los del agrupamiento de vanos, y una
        # copia local es justo como se cuelan los vocabularios paralelos.
        from chec_local_interpreter.ranking_circuitos import NOMBRES_GRUPOS_VANO

        grupos = NOMBRES_GRUPOS_VANO

        def _grupo(indice):
            try:
                return grupos[int(indice)]
            except (TypeError, ValueError, IndexError):
                return "N/D"

        # La primera columna es lo MEDIDO cuando el artefacto lo trae. La cabecera decia
        # "UITI medido" y la celda traia `u_base`, que es la base del MODELO: dos
        # cantidades de naturaleza distinta, y la del modelo se desvia mucho de la
        # observada. El SIGNO no es fijo: 599 bolsas dan +34% agregado, y DON23L14 da
        # razones de 0,607 y 0,593 en V9 y V10 -- el modelo por DEBAJO -- y 1,032 en
        # V11. Bajo el rotulo "medido", ese sesgo se lee como un dato de la base.
        # Sin observado se cae a la base y se DICE en la cabecera.
        hay_medido = all(v.get("u_observado") is not None for v in vanos)
        rotulo_base = "UITI medido" if hay_medido else "UITI base del modelo"

        filas = []
        for vano in sorted(vanos, key=lambda v: -float(v.get("u_base") or 0.0))[:15]:
            delta = int(vano.get("delta_grupo") or 0)
            marca = "&#9660;" if delta < 0 else ("&#9650;" if delta > 0 else "&mdash;")
            base = float((vano.get("u_observado") if hay_medido else vano.get("u_base")) or 0.0)
            # Bajar de Alto a Medio-Alto es una mejora real, y sin decirlo se lee igual
            # que no moverse: medido sobre DON23L14 V9, 91 de 93 vanos en Alto reciben un
            # plan que baja el UITI y no cambia el grupo.
            baja = bool(vano.get("baja_de_grupo")) or delta < 0
            filas.append(
                "<tr>"
                f"<td style='text-align:left;'>{_escape(vano.get('fid'))}</td>"
                f"<td>{base:,.1f}</td>"
                f"<td>{float(vano.get('u_simulado') or 0.0):,.1f}</td>"
                f"<td>{_escape(_grupo(vano.get('clase_base')))}</td>"
                f"<td>{_escape(_grupo(vano.get('clase_simulada')))} {marca}</td>"
                f"<td>{'sí' if baja else 'no'}</td>"
                f"<td>{len(vano.get('pasos') or [])}</td>"
                "</tr>"
            )
        knobs = ", ".join(str(k) for k in (simulacion or {}).get("knobs_usados") or [])
        pie = (f"<p class='muted'>Palancas movidas (solo intervención): {_escape(knobs)}.</p>"
               if knobs else
               "<p class='muted'>Ninguna palanca de intervención disponible en esta "
               "ventana: las variables de escenario entran con su valor observado y no "
               "se mueven.</p>")
        return (
            "<h4>Escenario de disminución</h4>"
            "<div class='table-scroll'><table class='compact-table'>"
            f"<thead><tr><th>Vano</th><th>{rotulo_base}</th>"
            "<th>UITI simulado</th><th>Grupo actual</th><th>Grupo simulado</th>"
            "<th>Baja de grupo</th><th>Pasos</th></tr></thead>"
            f"<tbody>{''.join(filas)}</tbody></table></div>{pie}"
        )

    def _render_inference_layout(results, analysis):
        """Una seccion por VENTANA estudiada.

        Aqui vivia un layout que buscaba cuatro claves fijas del camino MGCECDL
        (`top_uiti_periodo`, `top_frecuencia_periodo` y sus dos gemelas de puntos
        criticos). Desde el port al MIL `prepare` escribe los escenarios por VENTANA, asi
        que ninguna de las cuatro coincidia y la seccion de figuras del modelo salia
        VACIA en todos los informes, sin un solo mensaje.
        """
        if not results:
            return "", ""
        analysis = analysis or {}
        analisis_por_nombre = {
            str(e["nombre"]): e
            for e in (analysis.get("escenarios") or [])
            if isinstance(e, dict) and e.get("nombre")
        }

        def _interpretacion(contexto):
            nombre = str((contexto or {}).get("nombre") or "")
            return str((analisis_por_nombre.get(nombre) or {}).get("interpretacion") or "").strip()

        secciones = []
        for ventana in sorted(results, key=_orden_ventana):
            resultado = results.get(ventana)
            if not isinstance(resultado, dict):
                continue
            contexto = resultado.get("contexto") or {}
            periodo = str(contexto.get("periodo") or "")
            titulo = f"Ventana {ventana}" + (f" ({periodo})" if periodo else "")

            partes = [f"<h3>{_escape(titulo)}</h3>"]
            texto = _interpretacion(contexto)
            if texto:
                partes.append(f"<div class='content-box'>{_text_to_items(texto)}</div>")

            # Un grafo ausente se EXPLICA. Callarlo se lee como que la intervencion no
            # movio nada, que es lo contrario de "no hay vanos suficientes para
            # reconstruirlo".
            # A la mitad y centrado: el anillo es CUADRADO, asi que a ancho completo se
            # comia una franja del informe tan alta como ancha. Se reduce lo que se VE y
            # no el lienzo: encogiendo el PNG los rotulos de las variables se vuelven
            # ilegibles, que es lo unico que el anillo tiene que dejar leer.
            html_grafo = _figure_html(resultado.get("fig_grafo"), f"Grafo - {titulo}")
            if html_grafo:
                html_grafo = f"<div class='figura-mitad'>{html_grafo}</div>"
            if not html_grafo and resultado.get("grafo_motivo"):
                partes.append(
                    f"<div class='content-box'><em>{_escape(resultado['grafo_motivo'])}</em></div>")

            paneles = [
                _chart_panel(f"Serie por ventana - {titulo}",
                             _figure_html(resultado.get("fig_serie"), titulo)),
                _chart_panel(f"Relevancia hacia UITI mínimo - {titulo}",
                             _figure_html(resultado.get("fig_barras"), titulo)),
                _chart_panel(f"UITI medido vs estimado - {titulo}",
                             _figure_html(resultado.get("fig_uiti"), titulo)),
                _chart_panel(f"Qué variables se mueven juntas — {titulo}", html_grafo),
            ]
            partes.append(
                f"<div class='chart-grid two-col'>{''.join(p for p in paneles if p)}</div>")

            por_grupo = contexto.get("variables_por_grupo") or {}
            partes.append(_tabla_variables(
                por_grupo.get("Intervencion"),
                "Variables de intervención",
                "Obra que una cuadrilla puede ejecutar. Es lo que sostiene una orden de "
                "trabajo.",
            ))
            partes.append(_tabla_variables(
                por_grupo.get("Escenario"),
                "Variables de escenario",
                "Describen la condición en que ocurre el problema. No se ejecutan: "
                "entran al modelo con el valor observado de cada vano.",
            ))
            partes.append(_tabla_simulacion(contexto.get("simulacion")))
            secciones.append("\n".join(p for p in partes if p))

        if not secciones:
            return "", ""

        hallazgos = [str(h).strip() for h in (analysis.get("hallazgos") or []) if str(h).strip()]
        cabecera = []
        if hallazgos:
            cabecera.append(
                "<div class='summary-box'><h3 style='margin-top:0;'>Síntesis del modelo "
                "sobre las ventanas estudiadas</h3>"
                + _list_to_items(hallazgos, max_items=5) + "</div>")

        return "\n".join(cabecera), (
            "<h2>Diagnóstico y simulación por ventana</h2>" + "\n".join(secciones))


    # ------------------------------------------------------------------ cabecera
    # Los valores generales del circuito, ANTES de la barra del ranking. La barra
    # situa al circuito entre los demas, y esa pregunta solo tiene sentido cuando ya
    # se sabe de que circuito se habla -- que tan largo es, cuantos vanos estan
    # senalados, cuanto pesa. Antes eso no estaba en ninguna parte del informe.
    #
    # `all_circuits_df` y no `raw_df`: la ficha es COMPARATIVA (puesto, banda, aporte
    # al total) y `raw_df` viene ya recortado al circuito estudiado. Con uno solo, el
    # ranking mete a todo el mundo en la banda mas alta -- que es exactamente como en
    # su dia TODOS los informes decian "Riesgo Muy Alto".
    df_comparativo = all_circuits_df if all_circuits_df is not None else raw_df
    ficha = ficha_general(df_comparativo, primary_circuit,
                          start_date=start_date, end_date=end_date)
    ficha_html = tabla_ficha_html(ficha)
    clasificacion_html = tabla_clasificacion_html(
        df_comparativo, primary_circuit, start_date=start_date, end_date=end_date)

    # Como se arman las bolsas del modelo. Va al principio porque TODO lo que viene
    # despues -- la tabla de ventanas, el mapa, el diagnostico -- esta contado sobre
    # esta rejilla, y sin ella el lector no tiene como interpretar "V6".
    ventanas_explicacion_html = (
        "<div class='summary-box'><h3 style='margin-top:0;'>Cómo se construyen las "
        "ventanas</h3>"
        "<ul class='report-list'>"
        "<li>El período se recorre con <b>ventanas de treinta días que avanzan de "
        "quince en quince</b>. Cada ventana se solapa media ventana con la anterior y "
        "media con la siguiente.</li>"
        "<li>Dentro de una ventana, todos los registros de un mismo vano se juntan en "
        "una <b>bolsa</b>: la unidad que el modelo lee es la pareja "
        "<b>vano &times; ventana</b>, no el evento suelto.</li>"
        "<li>El solape existe para que un problema que ocurre a caballo entre dos "
        "meses no quede partido en dos mitades que ninguna ventana ve entera.</li>"
        "<li>Por eso mismo, los valores de UITI de las ventanas <b>no son aditivos</b>: "
        "sumar las once contabiliza varias veces los mismos registros. Cada ventana se "
        "lee contra las otras, nunca sumada con ellas.</li>"
        "<li>Las etiquetas <b>V1</b> a <b>V11</b> están fijadas sobre el rango completo "
        "de la base, no sobre el período de este informe: la <b>V6</b> de aquí es la "
        "misma V6 del modelo y la del mapa.</li>"
        "</ul></div>"
    )

    # Las ventanas y los vanos que mas pesan. El revisor los pidio en dos sitios y a
    # dos profundidades: nombrados en el resumen ejecutivo, y desglosados dentro de los
    # hallazgos. Se calculan UNA vez y se pintan en dos formas -- compacta y completa --
    # en vez de repetir el mismo bloque dos veces, que es como un informe termina
    # contestando la misma pregunta dos veces con dos numeros distintos.
    from chec_local_interpreter.ficha_circuito import _num as _numero_local

    def _serie_por_ventana() -> list:
        from chec_local_interpreter.context_builder import window_series_records

        try:
            return window_series_records(raw_df, circuito=primary_circuit)
        except Exception:
            # Hay caminos del informe que entregan eventos ya agregados, sin identidad
            # de vano. Sin serie se pierden las subsecciones que dependen de ella, no
            # el informe.
            return []

    serie_ventanas = _serie_por_ventana()
    ventanas_principales = [
        r for r in sorted(serie_ventanas, key=lambda r: -float(r.get("uv") or 0.0))[:3]
        if float(r.get("uv") or 0.0) > 0
    ]

    # Sostenida, puntual o intermitente. Calculado, no narrado: ver
    # `ficha_circuito.tipo_de_afectacion` para por que este veredicto no se le pide al
    # agente. El bloque lleva siempre las dos cifras que lo sostienen.
    afectacion_html_bloque = afectacion_html(tipo_de_afectacion(serie_ventanas))
    impacto_vanos = vanos_de_mayor_impacto(raw_df, primary_circuit, tope=5)

    # Cuales de las once ventanas tienen escenario, diagnostico y plan detras. Sin
    # esta marca, las once filas de la tabla se leen como equivalentes y quien busque
    # el analisis de la ventana que esta mirando no lo encuentra en ocho de los once
    # casos.
    #
    # TRES fuentes porque las tres existen por separado: `inference_results` trae las
    # figuras, `inference_analysis` la interpretacion, y el sidecar de mapas la marca
    # de su deslizador. Un informe rearmado desde los `.out.json` archivados tiene la
    # segunda y no la primera, y con una sola fuente perdia la marca en silencio.
    _mapas = ([mapas_ventana] if isinstance(mapas_ventana, dict)
              else list(mapas_ventana or []))
    _escenarios = (inference_analysis or {}).get("escenarios") or []

    def _ventana_del_escenario(escenario) -> str:
        """La etiqueta de ventana de un escenario del analisis.

        Medido sobre una corrida archivada: el escenario NO trae clave `ventana`, solo
        `nombre: "DON23L13 -- ventana V6"`. Exigir la clave dejaba la marca apagada en
        todos los informes rearmados desde disco, sin un solo aviso.
        """
        if not isinstance(escenario, dict):
            return ""
        if escenario.get("ventana"):
            return str(escenario["ventana"])
        hallazgo = _re_items.search(r"\bventana\s+(V\d+)\b",
                                    str(escenario.get("nombre") or ""),
                                    _re_items.IGNORECASE)
        return hallazgo.group(1) if hallazgo else ""

    ventanas_estudiadas = tuple(sorted(
        {str(v) for v in (inference_results or {})}
        | {v for v in (_ventana_del_escenario(e) for e in _escenarios) if v}
        | {str(m.get("ventana")) for m in _mapas
           if isinstance(m, dict) and m.get("estudiada") and m.get("ventana")}
    ))

    def _items_ricos(items: list[str]) -> str:
        """Una lista cuyos items YA traen marcado.

        `_envolver_items` escapa cada item, que es lo correcto para prosa de agente y
        lo contrario de lo que hace falta aqui: pasarle un `<b>` dibuja literalmente
        `&lt;b&gt;`. Lo variable se escapa en el sitio donde se interpola.
        """
        if not items:
            return ""
        return ("<ul class='report-list'>"
                + "".join(f"<li>{i}</li>" for i in items) + "</ul>")

    def _resumen_impacto_html() -> str:
        """Version compacta, para el resumen ejecutivo: solo los nombres."""
        partes = []
        if ventanas_principales:
            partes.append(
                "<h4>Ventanas de mayor aporte UITI</h4>"
                + _items_ricos([
                    f"<b>{_escape(r['w'])}</b> ({_escape(r.get('periodo', ''))}): "
                    f"UITI {_numero_local(float(r.get('uv') or 0.0), 1)} sobre "
                    f"{_numero_local(float(r.get('vanos') or 0))} vanos"
                    for r in ventanas_principales
                ])
            )
        if impacto_vanos["por_uiti"]:
            coincidentes = impacto_vanos["coincidentes"]
            resumen = (
                f"Vanos señalados por los dos criterios a la vez: "
                f"{', '.join(_escape(f) for f in coincidentes)}."
                if coincidentes else
                "Ningún vano está en las dos listas: el que concentra UITI y el que "
                "más se repite son vanos distintos."
            )
            partes.append(
                "<h4>Vanos de mayor impacto</h4>"
                f"<p style='margin:4px 0;'>{resumen} El desglose por criterio está "
                f"en <b>2.3 Análisis de vanos</b>.</p>"
            )
        return "".join(partes)

    def _analisis_vanos_html() -> str:
        """Version completa, para los hallazgos: los dos criterios y su interseccion.

        Un vano puede concentrar UITI en una sola salida larga y otro aparecer en todas
        las ventanas con poco cada vez. Son dos problemas distintos y se atienden
        distinto, asi que el informe no puede quedarse con uno de los dos criterios y
        llamarlo "los vanos importantes".
        """
        if not impacto_vanos["por_uiti"]:
            return ""

        def _lista(clave, formato):
            return _items_ricos([formato(v) for v in impacto_vanos[clave]])

        coincidentes = (
            _items_ricos([f"<b>{_escape(f)}</b>"
                          for f in impacto_vanos["coincidentes"]])
            if impacto_vanos["coincidentes"]
            else "<p class='muted'>Ninguno.</p>"
        )
        return (
            "<h3>2.3 Análisis de vanos</h3>"
            "<div class='columnas-vanos'>"
            "<div><h5>Por UITI acumulado</h5>"
            + _lista("por_uiti",
                     lambda v: f"{_escape(v['fid'])} — "
                               f"{_numero_local(v['uiti'], 1)}")
            + "</div><div><h5>Por número de apariciones</h5>"
            + _lista("por_apariciones",
                     lambda v: f"{_escape(v['fid'])} — "
                               f"{_numero_local(v['apariciones'])} registros")
            + "</div><div><h5>En las dos listas</h5>"
            + coincidentes
            + "</div></div>"
            "<p class='muted'>Un vano en las <b>dos</b> listas lo está con cualquiera "
            "de los dos criterios: es el candidato que no depende de cómo se haya "
            "decidido mirar. Estos vanos se señalan por su historia; cuáles intervenir "
            "y qué mover en cada uno lo dice el diagnóstico por ventana.</p>"
        )

    resumen_impacto_html = _resumen_impacto_html()
    analisis_vanos_html = _analisis_vanos_html()

    period_str = f"{start_date or 'Inicio'} a {end_date or 'Fin'}"
    title_str = f"Reporte Criticidad - Circuito: {primary_circuit}"

    # Adjust subtitle if no LLM data is present
    model_display = f"{llm_provider} ({llm_model})" if llm_model and llm_model != "Desconocido" else llm_provider
    if validation_data:
        subtitle_info = f"Período de análisis: {period_str} | Modelo LLM: {model_display}"
        if tokens_input is not None or tokens_output is not None:
            # `token_source` (design `reporte-perf-optimization` item 4)
            # labels whether these counts are real (measured), partially
            # real (mixed), or the char/4 approximation (estimated) -- see
            # `report_pipeline._resolve_token_usage`. Exact ("measured")
            # counts drop the "~" prefix; anything with an estimated
            # component keeps it, since it is still an approximation.
            token_label, prefix = _token_source_label(token_source)
            tokens_in_str = f"{prefix}{tokens_input:,}" if tokens_input is not None else "N/D"
            tokens_out_str = f"{prefix}{tokens_output:,}" if tokens_output is not None else "N/D"
            if token_source == "measured":
                split_label = f"Tokens de entrada/salida medidos ({token_label})"
            else:
                split_label = (
                    f"Tokens parciales disponibles ({token_label}; no representan el consumo global)"
                )
            subtitle_info += (
                "<br><span style='font-size: 0.85em; color: #94a3b8;'>"
                f"{split_label}: entrada {tokens_in_str} | salida {tokens_out_str}"
                "</span>"
            )
        if tokens_total is not None or elapsed_seconds is not None:
            # Independent of the entrada/salida block above -- this line
            # covers the TOTAL across every agent stage that ran, including
            # sub-agents dispatched in parallel (see `_resolve_token_usage`'s
            # `"total"`-only sidecar shape), plus the run's total wall-clock
            # execution time. `token_total_source` is independent because a
            # runtime may expose measured totals without an input/output split.
            effective_total_source = token_total_source or token_source
            token_label, prefix = _token_source_label(effective_total_source)
            if tokens_total is not None:
                tokens_total_part = (
                    "Tokens totales (todas las etapas, incl. sub-agentes/corridas en paralelo) "
                    f"{token_label}: {prefix}{tokens_total:,}"
                )
            else:
                tokens_total_part = "Uso total de tokens: no disponible"
            time_str = _format_elapsed_seconds(elapsed_seconds) if elapsed_seconds is not None else "N/D"
            time_part = f"Tiempo total de ejecución: {time_str}"
            subtitle_info += (
                "<br><span style='font-size: 0.85em; color: #94a3b8;'>"
                f"{tokens_total_part} | {time_part}"
                "</span>"
            )
        # El desglose por etapa YA NO va aqui. Vivia en el subtitulo como una
        # tabla gris de 0.8em -- tres filas de numeros donde nada decia que dos
        # de esas etapas corren A LA VEZ, que es justamente el hecho que
        # explica por que el reloj de pared es menor que su suma. Ahora se
        # dibuja como figura al final del informe (`seccion_agentes_html`),
        # con el mismo `stage_breakdown` y sin datos nuevos.
    else:
        subtitle_info = f"Período de análisis: {period_str} | (Solo visualización, sin análisis LLM)"

    # El escudo y el pie salen de `informe_estilo`, que es de donde los saca tambien el
    # informe gerencial. Dos implementaciones del mismo `data:` URI es como los dos
    # informes se separaron la primera vez.
    escudo_html = escudo_chec_html()
    # Como se construyo el informe: la linea de tiempo de los agentes, dibujada
    # desde el MISMO `stage_breakdown` que ya llega por parametro. Va pegada al
    # pie que dice quien lo produjo, porque es la respuesta a esa misma frase.
    seccion_agentes = seccion_agentes_html(
        linea_desde_desglose(
            stage_breakdown,
            circuito=primary_circuit,
            fecha_inicio=start_date,
            fecha_fin=end_date,
        )
    )

    pie_html = pie_agentes_html()

    title_html = f"Reporte Criticidad - Circuito: {primary_circuit}<br><span style='font-size: 0.6em; color: #64748b;'>{subtitle_info}</span>"

    html_maps_section = _mapas_ventana_html()

    html_inference_characterization, html_inference_critical = _render_inference_layout(inference_results, inference_analysis)
    characterization_visuals_html = f"{html_maps_section}{html_inference_characterization}"
    html_expert_alignment = render_expert_alignment_tab(expert_alignment_analysis)

    llm_sections_html = ""
    # Se declara aqui y no dentro del `if`: lo consume la seccion de diagnostico por
    # ventana, que se arma pase lo que pase con el analisis descriptivo.
    inferencias_html = ""
    if validation_data:
        exec_summary = validation_data.get('executive_summary', [])
        if isinstance(exec_summary, list):
            exec_summary = " ".join(exec_summary)

        # La CARACTERIZACION ya no es una seccion propia. Era el tercer sitio del
        # informe que describia al circuito -- despues del resumen ejecutivo y de los
        # hallazgos --, con los mismos numeros redactados de otra manera; la revision
        # pidio eliminarla. Lo que si aporta -- las justificaciones fisico-logicas por
        # modo -- se muda a Hallazgos, que es donde el lector ya esta preguntandose
        # por que ocurre lo que la seccion acaba de describir.
        char_data = validation_data.get('circuit_characterization', {})
        if isinstance(char_data, dict):
            char_text = char_data.get('text', '')

            char_html = _text_to_items(char_text)
            # Aqui salian dos listas de "top P97 vanos", una por UITI y otra por
            # frecuencia. Eran un TERCER criterio para senalar vanos importantes,
            # compitiendo con el ranking del cuaderno 02 y con el diagnostico de 15 vanos
            # del 06: tres tablas contestando "cuales vanos" con tres metodos distintos,
            # y quien lee no tiene como saber cual seguir. La respuesta es el diagnostico,
            # que ademas dice QUE mover.
            #
            # La revision pidio dos cosas para las ventanas: una TABLA con fechas,
            # aporte UITI, registros y vanos, y el resumen COMPARATIVO entre ellas. La
            # tabla se calcula (`tabla_ventanas_html`) en vez de pedirsela en prosa a
            # un agente; la comparacion se queda en prosa, que es lo que la tabla no
            # puede dar, y se pinta debajo de ella.
            justifications = char_data.get('probable_justifications_rules', [])
            if justifications:
                char_html += "<h4>🔗 Justificaciones Físico-Lógicas (Análisis por Modos)</h4><ul>"
                for j in justifications:
                    if isinstance(j, dict):
                        modo = j.get('modo', '')
                        # En castellano y con el codigo entre parentesis. Se hace AQUI
                        # y no pidiendoselo al agente: asi no depende de que se acuerde,
                        # y la traduccion es la misma en todo el informe.
                        _crudas = j.get('variables_asociadas', [])
                        vars_assoc = (", ".join(nombre_con_codigo(str(v)) for v in _crudas)
                                      if isinstance(_crudas, list) else str(_crudas))
                        just_fis = j.get('justificacion_fisico_logica', '')
                        ana = j.get('analisis_causas', '')
                        char_html += f"<li style='margin-bottom: 8px;'><strong>Modo {NOMBRE_LEGIBLE_GRUPO.get(modo, modo)} ({vars_assoc}):</strong> {just_fis}<br><span style='font-size: 0.95em; color: #475569;'><em>Análisis:</em> {ana}</span></li>"
                    else:
                        char_html += f"<li>{_mayuscula_inicial(str(j))}</li>"
                char_html += "</ul>"
        else:
            char_html = str(char_data)

        hypothesis = validation_data.get('cause_hypothesis_note', 'No se generó hipótesis de causa en este reporte.')

        key_findings = validation_data.get('key_findings', [])
        findings_texts = []
        for f in key_findings:
            if isinstance(f, dict) and f.get('text'):
                findings_texts.append(f.get('text'))
            elif isinstance(f, str):
                findings_texts.append(f)

        # Las tres notas de lectura que la revision pidio dejar fijas al frente de los
        # hallazgos. No dependen de lo que el agente escriba: son propiedades de la
        # rejilla y del alcance del analisis, y sin ellas la tabla de ventanas se lee
        # como una serie de once medidas independientes que se pueden sumar.
        notas_hallazgos_html = (
            "<div class='content-box' style='background:#f8fafc;'>"
            "<ul class='report-list'>"
            "<li>Las ventanas se traslapan quince días entre sí, de manera que sus "
            "valores de UITI <b>no son aditivos</b>.</li>"
            "<li>La suma de las once ventanas contabiliza varias veces los mismos "
            "registros vano-evento.</li>"
            "<li>Esta lectura describe <b>lo observado</b> en el período y "
            "<b>no anticipa el comportamiento futuro</b> del circuito.</li>"
            "</ul></div>"
        )

        findings_html = ""
        if findings_texts:
            # El titulo de este bloque repetia palabra por palabra el de la seccion que
            # lo contiene. Ahora nombra lo que el bloque hace -- describir el
            # comportamiento del circuito en el periodo -- que es lo que lo distingue
            # de las subsecciones que vienen despues.
            findings_html += (
                "<div class='summary-box'><h3 style='margin-top:0;'>"
                "Lectura del comportamiento en el período</h3>"
                + _text_to_items(" ".join(findings_texts))
                + "</div>"
            )

        # Las inferencias del modelo bajan a la subseccion de ventanas: estan enfocadas
        # en la ventana, que es exactamente donde el revisor las pidio. Sueltas entre
        # los hallazgos abrian un bloque nuevo entre lo observado y lo proyectado sin
        # decir cual era cual -- justo lo que las notas de arriba acaban de separar.
        inferencias = (inference_analysis or {}).get('inferencias_predictivas', [])
        inferencias_html = ""
        if inferencias:
            inferencias_html = ("<div class='summary-box'><h4 style='margin-top:0;'>"
                                "Inferencias complementarias del modelo</h4>"
                                "<p class='muted' style='margin-top:0;'>Lo que el "
                                "modelo proyecta sobre estas ventanas. A diferencia de "
                                "lo anterior, esto no describe lo observado.</p>"
                                "<ul class='report-list'>")
            for inf in inferencias:
                r = inf.get('riesgo', '')
                h = inf.get('horizonte', '')
                j = inf.get('justificacion_modelo', '')
                inferencias_html += (
                    f"<li><b>{_escape(_mayuscula_inicial(str(h)))}:</b> "
                    f"{_escape(_mayuscula_inicial(str(r)))} &mdash; "
                    f"<i>{_escape(_mayuscula_inicial(str(j)))}</i></li>"
                )
            inferencias_html += "</ul></div>"

        # La lectura comparativa entre ventanas, que es lo que la tabla no da: cual
        # pesa mas que cual y por que. Va DEBAJO de la tabla, no en su lugar.
        #
        # Se filtran los items que son SOLO una etiqueta. El esquema pide
        # `ventanas_estudiadas` y hay corridas donde el agente entrega `["V6", "V7",
        # "V11"]`: eso pintaba un titulo y tres vinetas que decian `V6`, `V7` y `V11`,
        # al lado de una tabla que ya trae las once ventanas con sus cifras. Un bloque
        # sin contenido se lee como que falta algo, no como que no habia nada.
        ventanas_narradas = [
            str(v).strip() for v in
            ((char_data.get('ventanas_estudiadas', []) or [])
             if isinstance(char_data, dict) else [])
            if len(str(v).strip().split()) > 1
        ]
        comparacion_ventanas_html = (
            "<h4>Lectura comparativa entre ventanas</h4>"
            + _list_to_items([str(v) for v in ventanas_narradas])
        ) if ventanas_narradas else ""

        # 2.5 y 2.7 son campos OPCIONALES del contrato del historico: las corridas
        # anteriores a la revision no los traen y esas subsecciones sencillamente no se
        # dibujan. Degradar en silencio es lo correcto aqui -- un informe archivado se
        # vuelve a pintar sin ellas, no revienta.
        variables_relevantes = [
            str(v).strip() for v in (validation_data.get('variables_relevantes') or [])
            if str(v).strip()
        ]
        variables_relevantes_html = (
            "<h3>2.5 Análisis de variables relevantes</h3>"
            f"<div class='content-box'>{_list_to_items(variables_relevantes, max_items=5)}</div>"
        ) if variables_relevantes else ""

        # `period_synthesis` YA era la evolucion temporal: el contrato lo define como
        # "el unico campo que habla de trayectoria". Lo que faltaba no era el dato, era
        # que fuera subseccion propia y no un bloque suelto al final del numeral.
        synthesis = validation_data.get('period_synthesis', '')
        sintesis_periodo_html = (
            f"<h3>2.6 Análisis de evolución temporal</h3><div class='content-box'>"
            f"{_text_to_items(synthesis)}</div>" if synthesis else "")

        conclusion = str(validation_data.get('conclusion_general') or '').strip()
        conclusion_html = (
            f"<h3>2.7 Conclusión general</h3><div class='content-box'>"
            f"{_text_to_items(conclusion)}</div>" if conclusion else "")

        llm_sections_html = f"""
            <div class="summary-box">
                <h2 style="margin-top: 0;">1. Resumen ejecutivo</h2>
                {_text_to_items(exec_summary)}
                {resumen_impacto_html}
            </div>

            <h2>2. Hallazgos del análisis descriptivo</h2>
            {notas_hallazgos_html}

            <h3>2.1 Tipo de afectación</h3>
            {afectacion_html_bloque}
            {findings_html}

            <h3>2.2 Ventana de mayor aporte y ventanas estudiadas</h3>
            {tabla_ventanas_html(raw_df, primary_circuit, estudiadas=ventanas_estudiadas)}
            {comparacion_ventanas_html}
            {inferencias_html}

            {analisis_vanos_html}

            <h3>2.4 Justificaciones y estado del circuito</h3>
            <div class="content-box">
                {char_html}
            </div>
            {characterization_visuals_html}
            {variables_relevantes_html}
            {sintesis_periodo_html}
            {conclusion_html}

            <div class="summary-box" style="background: #fffbeb; border-left: 5px solid #fbbf24;">
                <h2 style="margin-top: 0; color: #b45309;">3. Posible Causa Raíz (Hipótesis)</h2>
                {_hipotesis_html(hypothesis)}
            </div>
        """
    elif characterization_visuals_html:
        llm_sections_html = f"""
            <h2>Estado del circuito</h2>
            {characterization_visuals_html}
        """

    # Aqui iba la grafica diaria de puntos criticos. Se fue con la deteccion: era la
    # unica pieza del informe que hablaba de DIAS, una rejilla que ni el ranking del 02 ni
    # el diagnostico del 06 comparten. La serie por ventana de cada escenario ocupa su
    # sitio, y esa si esta en la unidad del resto del informe.
    report_tab_html = f"""
            {ficha_html}

            {ventanas_explicacion_html}

            <h2>Clasificación de criticidad del circuito</h2>
            <div class="chart-container">{html_clusters}</div>
            {clasificacion_html}

            {llm_sections_html}

            {html_inference_critical}
    """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>{title_str}</title>
        <style>
{CSS_IDENTIDAD}
            .summary-box {{ background: #eff6ff; padding: 15px 18px; border-left: 5px solid #3b82f6; border-radius: 6px; margin-bottom: 20px; }}
            .content-box {{ background: #ffffff; padding: 15px 18px; border: 1px solid #cbd5e1; border-radius: 6px; margin-bottom: 20px; }}
            ul.report-list {{ margin: 6px 0 4px 0; padding-left: 20px; list-style: disc; }}
            ul.report-list li {{ margin-bottom: 5px; line-height: 1.55; font-size: 0.95rem; }}
            .chart-container {{ margin-bottom: 40px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
            /* Las tablas de la revision: ficha del circuito, clasificacion y ventanas.
               Un solo estilo para las tres, para que el informe no tenga tres tablas
               con tres aspectos distintos diciendo cosas del mismo orden. */
            .tabla-informe {{ border-collapse: collapse; width: 100%;
                              font-size: 0.92rem; margin: 6px 0 4px 0; }}
            .tabla-informe th, .tabla-informe td {{ border: 1px solid #e2e8f0;
                              padding: 6px 10px; text-align: left; }}
            .tabla-informe thead th {{ background: #f1f5f9; color: #1e3a8a;
                              font-weight: 700; }}
            .tabla-informe td.num {{ text-align: right;
                              font-variant-numeric: tabular-nums; }}
            .tabla-informe tbody tr:nth-child(even) {{ background: #f8fafc; }}
            .tabla-informe .fila-destacada {{ background: #dbeafe !important;
                              font-weight: 700; }}
            .tabla-informe.ficha th {{ background: #f8fafc; width: 62%;
                              font-weight: 600; }}
            .ficha-circuito {{ background: #ffffff; border: 1px solid #cbd5e1;
                              border-left: 5px solid #1e3a8a; border-radius: 6px;
                              padding: 14px 18px; margin-bottom: 20px; }}
            .ficha-titular {{ margin: 0 0 10px 0; font-size: 1.05rem; color: #0f172a; }}
            /* 208 filas abiertas empujan el informe entero: la tabla completa va
               plegada y con su propio desplazamiento. */
            .tabla-desplazable {{ max-height: 460px; overflow-y: auto; }}
            .tabla-clasificacion details {{ margin-top: 8px; }}
            .tabla-clasificacion summary {{ cursor: pointer; color: #1d4ed8;
                              font-weight: 600; }}
            .columnas-vanos {{ display: grid; gap: 14px; margin-top: 6px;
                              grid-template-columns: repeat(3, minmax(0, 1fr)); }}
            .columnas-vanos h5 {{ margin: 0 0 4px 0; color: #1e3a8a; font-size: 0.9rem; }}
            @media (max-width: 900px) {{ .columnas-vanos {{ grid-template-columns: 1fr; }} }}
            /* La frase que enmarca la hipotesis, como parrafo y no como una vineta mas. */
            .hipotesis-contexto {{ margin: 0 0 8px 0; line-height: 1.55; }}
            .chart-grid {{ display: grid; gap: 18px; margin-bottom: 28px; }}
            .chart-grid.two-col {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .chart-panel {{ border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #ffffff; min-width: 0; }}
            .chart-panel h3 {{ margin: 0; padding: 10px 14px; background: #f8fafc; color: #1e3a8a; font-size: 15px; border-bottom: 1px solid #e2e8f0; }}
            .embedded-figure {{ display: block; width: 100%; height: auto; padding: 12px; box-sizing: border-box; }}
            /* El anillo del grafo, a la mitad y centrado. Cuadrado a ancho completo
               ocupa tanto alto como ancho y desplaza al resto de la seccion. */
            .figura-mitad .embedded-figure {{ width: 50%; margin: 0 auto; }}
            /* UN visor de mapa: las capas se apilan en el mismo sitio y el deslizador
               elige cual se ve. Tres mapas seguidos obligan a bajar y subir, y a esa
               distancia la comparacion se hace de memoria. */
            .visor-mapas {{ border: 1px solid #e2e8f0; border-radius: 8px;
                            background: #ffffff; padding: 12px; }}
            .mapa-ventana {{ display: none; }}
            .mapa-ventana.activa {{ display: block; }}
            .mapa-control {{ margin: 0 0 12px 0; }}
            .mapa-fila-control {{ display: flex; align-items: center; gap: 8px; }}
            .mapa-deslizador {{ flex: 1; accent-color: #2563eb; }}
            .mapa-flecha {{ appearance: none; border: 1px solid #cbd5e1; background: #f8fafc;
                            color: #1e3a8a; border-radius: 6px; width: 30px; height: 28px;
                            cursor: pointer; font-size: 12px; line-height: 1; }}
            .mapa-flecha:hover {{ background: #e2e8f0; }}
            .mapa-flecha[disabled] {{ opacity: .4; cursor: default; }}
            .mapa-barra {{ display: flex; justify-content: flex-end; margin-bottom: 8px; }}
            .mapa-pantalla-completa {{ appearance: none; border: 1px solid #cbd5e1;
                            background: #f8fafc; color: #1e3a8a; border-radius: 6px;
                            padding: 5px 10px; cursor: pointer; font-weight: 600;
                            font-size: 12px; }}
            .mapa-pantalla-completa:hover {{ background: #e2e8f0; }}
            /* En pantalla completa el mapa toma el alto real de la pantalla. Sin esto
               el navegador amplia el marco y deja el iframe en sus 380 px, con el
               resto en negro: la ampliacion no serviria para nada. */
            .visor-mapas:fullscreen {{ background: #ffffff; padding: 16px;
                                       display: flex; flex-direction: column; }}
            .visor-mapas:fullscreen .mapa-ventana.activa {{ flex: 1; display: flex;
                                       flex-direction: column; }}
            .visor-mapas:fullscreen iframe.embedded-map-frame {{ flex: 1; height: auto !important; }}
            .mapa-marcas {{ display: flex; color: #64748b; font-size: 12px;
                            margin-top: 2px; }}
            /* Las tres ventanas que el informe estudia, entre las once del deslizador:
               son las unicas con escenario, diagnostico y plan detras. */
            .marca-estudiada {{ color: #1e3a8a; font-weight: 700; }}
            .graph-panel iframe {{ width: 100%; height: 620px; border: 0; background: #ffffff; }}
            .graph-actions {{ padding: 10px 14px; border-bottom: 1px solid #e2e8f0; background: #ffffff; }}
            .graph-actions a {{ color: #1d4ed8; font-weight: 600; text-decoration: none; }}
            .item-details span {{ display: block; margin-top: 4px; }}
            .muted {{ color: #64748b; margin: 6px 0 4px 0; }}
            .tabs {{ margin-top: 18px; }}
            .tab-nav {{ display: flex; gap: 8px; border-bottom: 1px solid #cbd5e1; margin-bottom: 20px; flex-wrap: wrap; }}
            .tab-button {{ appearance: none; border: 1px solid #cbd5e1; border-bottom: 0; background: #f8fafc; color: #1e3a8a; padding: 10px 14px; border-radius: 6px 6px 0 0; font-weight: 700; cursor: pointer; }}
            .tab-button.active {{ background: #ffffff; color: #0f172a; box-shadow: inset 0 3px 0 #2563eb; }}
            .tab-panel {{ display: none; }}
            .tab-panel.active {{ display: block; }}
            @media (max-width: 900px) {{ .chart-grid.two-col {{ grid-template-columns: 1fr; }} }}
        </style>
        {html_plotlyjs}
    </head>
    <body>
        <div class="container">
            {escudo_html}
            <h1>📊 {title_html}</h1>
            <div class="tabs">
                <div class="tab-nav" role="tablist" aria-label="Secciones del reporte">
                    <button class="tab-button active" type="button" role="tab" aria-selected="true" aria-controls="tab-informe" id="tab-button-informe" data-tab-target="tab-informe">Informe</button>
                    <button class="tab-button" type="button" role="tab" aria-selected="false" aria-controls="tab-expertos" id="tab-button-expertos" data-tab-target="tab-expertos">Comparación con reportes expertos</button>
                </div>
                <section class="tab-panel active" role="tabpanel" id="tab-informe" aria-labelledby="tab-button-informe">
                    {report_tab_html}
                </section>
                <section class="tab-panel" role="tabpanel" id="tab-expertos" aria-labelledby="tab-button-expertos">
                    {html_expert_alignment}
                </section>
            </div>
            {seccion_agentes}
            {pie_html}
        </div>
        <script>
            document.querySelectorAll('.tab-button').forEach(function(button) {{
                button.addEventListener('click', function() {{
                    var targetId = button.getAttribute('data-tab-target');
                    document.querySelectorAll('.tab-button').forEach(function(item) {{
                        item.classList.toggle('active', item === button);
                        item.setAttribute('aria-selected', item === button ? 'true' : 'false');
                    }});
                    document.querySelectorAll('.tab-panel').forEach(function(panel) {{
                        var isActive = panel.id === targetId;
                        panel.classList.toggle('active', isActive);
                        // Plotly figures rendered while their tab was still
                        // `display:none` measure a 0px-wide container and get
                        // stuck at a small fallback size (Plotly never
                        // auto-resizes without a visibility/resize signal).
                        // Force a resize now that the panel is actually
                        // visible so charts expand to the panel's real width.
                        if (isActive && window.Plotly) {{
                            panel.querySelectorAll('.plotly-graph-div').forEach(function(graphDiv) {{
                                try {{ window.Plotly.Plots.resize(graphDiv); }} catch (e) {{}}
                            }});
                        }}
                        // Same 0px-container problem for the embedded Leaflet
                        // (folium) maps: their <iframe> was `display:none`
                        // at load time, so their fitBounds() centered on
                        // nothing. Tell each iframe's own window to re-fit
                        // now that its tab is actually visible.
                        if (isActive) {{
                            panel.querySelectorAll('iframe.embedded-map-frame').forEach(function(frame) {{
                                try {{
                                    if (frame.contentWindow) {{
                                        frame.contentWindow.dispatchEvent(new Event('resize'));
                                    }}
                                }} catch (e) {{}}
                            }});
                        }}
                    }});
                }});
            }});

            // El deslizador del mapa. Las capas ya estan dibujadas y apiladas: mover
            // el control solo cambia cual se ve, asi que no hay que esperar a nada ni
            // volver a pedir geometria.
            document.addEventListener('DOMContentLoaded', function() {{
                document.querySelectorAll('.visor-mapas').forEach(function(visor) {{
                    // El boton de pantalla completa existe aunque haya UNA sola
                    // ventana: ampliar el trazado no tiene nada que ver con poder
                    // recorrer ventanas, y el deslizador si depende de que haya varias.
                    var ampliar = visor.querySelector('.mapa-pantalla-completa');
                    if (ampliar) {{
                        ampliar.addEventListener('click', function() {{
                            if (document.fullscreenElement === visor) {{
                                document.exitFullscreen();
                            }} else if (visor.requestFullscreen) {{
                                visor.requestFullscreen();
                            }}
                        }});
                        document.addEventListener('fullscreenchange', function() {{
                            var dentro = document.fullscreenElement === visor;
                            ampliar.textContent = dentro
                                ? '⤡ Salir de pantalla completa'
                                : '⤢ Ampliar a pantalla completa';
                            // El iframe de Leaflet midio su contenedor al cargarse. Al
                            // cambiar de tamano hay que decirselo o el mapa se queda
                            // encuadrado sobre el tamano viejo.
                            visor.querySelectorAll('iframe.embedded-map-frame').forEach(
                                function(frame) {{
                                    try {{
                                        if (frame.contentWindow) {{
                                            frame.contentWindow.dispatchEvent(
                                                new Event('resize'));
                                        }}
                                    }} catch (e) {{}}
                                }});
                        }});
                    }}

                    var deslizador = visor.querySelector('.mapa-deslizador');
                    if (!deslizador) {{ return; }}
                    var capas = visor.querySelectorAll('.mapa-ventana');
                    var marcas = visor.querySelectorAll('.mapa-marcas span');
                    var anterior = visor.querySelector('.mapa-anterior');
                    var siguiente = visor.querySelector('.mapa-siguiente');
                    var tope = parseInt(deslizador.max, 10);
                    function mostrar() {{
                        var i = parseInt(deslizador.value, 10);
                        capas.forEach(function(capa, k) {{
                            capa.classList.toggle('activa', k === i);
                        }});
                        marcas.forEach(function(marca, k) {{
                            marca.style.fontWeight = (k === i) ? '700' : '400';
                            marca.style.color = (k === i) ? '#1e3a8a' : '#64748b';
                        }});
                        // Una flecha que no lleva a ninguna parte se deshabilita en vez
                        // de no hacer nada: pulsar sin efecto se lee como una averia.
                        if (anterior) {{ anterior.disabled = (i <= 0); }}
                        if (siguiente) {{ siguiente.disabled = (i >= tope); }}
                    }}
                    function saltar(paso) {{
                        var i = parseInt(deslizador.value, 10) + paso;
                        deslizador.value = Math.min(tope, Math.max(0, i));
                        mostrar();
                    }}
                    if (anterior) {{
                        anterior.addEventListener('click', function() {{ saltar(-1); }});
                    }}
                    if (siguiente) {{
                        siguiente.addEventListener('click', function() {{ saltar(1); }});
                    }}
                    deslizador.addEventListener('input', mostrar);
                    mostrar();
                }});
            }});
        </script>
    </body>
    </html>
    """

    # Save to disk. Callers that can identify a report run should pass a
    # deterministic filename so metadata enrichment re-renders replace the same
    # artifact instead of leaving a model-less preliminary HTML next to the final one.
    os.makedirs(output_dir, exist_ok=True)
    if output_filename is None:
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        start_str = start_date.strftime("%Y%m%d") if hasattr(start_date, 'strftime') else str(start_date).replace('-', '') if start_date else "inicio"
        end_str = end_date.strftime("%Y%m%d") if hasattr(end_date, 'strftime') else str(end_date).replace('-', '') if end_date else "fin"
        output_filename = f"{primary_circuit}_{start_str}_{end_str}_{timestamp}.html"
    filepath = Path(output_dir) / output_filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    display(Markdown(f"✅ **Reporte generado y guardado exitosamente:** [{filepath.absolute()}]({filepath.absolute()})"))
    display(HTML(f'<a href="{filepath.absolute()}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #2563eb; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">Abrir Reporte en Nueva Pestaña</a>'))

    return filepath
