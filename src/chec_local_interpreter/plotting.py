from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from chec_local_interpreter.config import PROJECT_ROOT
from chec_local_interpreter.event_counts import count_unique_event_dates
from chec_local_interpreter.glosario_variables import nombre_con_codigo


import numpy as np
import plotly.graph_objects as go
import plotly.express as px

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def run_kmeans(data, n_clusters=5, max_iters=100, random_state=42):
    """Custom NumPy K-Means implementation."""
    np.random.seed(random_state)
    # Ensure we don't ask for more clusters than available data points
    n_clusters = min(n_clusters, data.shape[0])

    centroids = data[np.random.choice(data.shape[0], n_clusters, replace=False)]

    for _ in range(max_iters):
        distances = np.linalg.norm(data[:, np.newaxis] - centroids, axis=2)
        labels = np.argmin(distances, axis=1)
        new_centroids = np.array([
            data[labels == k].mean(axis=0) if np.any(labels == k) else centroids[k]
            for k in range(n_clusters)
        ])
        if np.allclose(centroids, new_centroids):
            break
        centroids = new_centroids

    return labels


# Single source of truth for the circuit-criticality tiers shared by the
# clustering chart (`plot_interactive_circuit_clustering`) and the LLM-facing
# context builder (`context_builder._compute_circuit_characterization`), so
# the chart legend and the report narrative never drift out of sync.
CRITICALITY_GROUP_LABELS: tuple[str, ...] = (
    "Riesgo Muy Alto", "Riesgo Alto", "Riesgo Medio-Alto", "Riesgo Medio-Bajo", "Riesgo Bajo"
)
CRITICALITY_GROUP_COLORS: tuple[str, ...] = ("#ef4444", "#f97316", "#eab308", "#84cc16", "#22c55e")


def compute_circuit_criticality_groups(raw_df, start_date=None, end_date=None, group_labels=None):
    """
    Compute per-circuit event-frequency / UITI_VANO-sum coordinates, K-Means
    cluster assignment, and ranked criticality label.

    Shared by `plot_interactive_circuit_clustering` (chart) and
    `context_builder._compute_circuit_characterization` (LLM context) so both
    call sites derive `criticidad` from a single source of truth.

    Parameters:
    - raw_df (pd.DataFrame): The main dataset containing 'CIRCUITO', 'UITI_VANO', and 'FECHA'.
    - start_date (str, optional): Start date string (e.g. '2023-01-01').
    - end_date (str, optional): End date string.
    - group_labels (sequence[str], optional): Tier labels ordered from most to
      least critical, overriding `CRITICALITY_GROUP_LABELS`. Its length sets
      the number of K-Means clusters. All callers (standalone agrupamiento
      chart, batch reports, informe-gerencial, context builder) share the
      same 5-tier default.

    Returns:
    - pd.DataFrame indexed by CIRCUITO with columns `event_count`,
      `uiti_vano_sum`, `cluster` (raw K-Means id), `criticidad` (ranked label
      from `group_labels`). Empty (same columns) if no data survives
      filtering.
    """
    group_labels = list(group_labels) if group_labels is not None else list(CRITICALITY_GROUP_LABELS)
    empty_columns = ["event_count", "uiti_vano_sum", "cluster", "criticidad", "centroid_distance"]

    df = raw_df.copy()

    # 1. Check if we need to filter by date and ensure FECHA is parsed safely
    if start_date is not None or end_date is not None:
        if 'FECHA' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['FECHA']):
                df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')

            fecha_dia = df['FECHA'].dt.floor("D")
            if start_date is not None:
                df = df[fecha_dia >= pd.to_datetime(start_date).floor("D")]
            if end_date is not None:
                df = df[fecha_dia <= pd.to_datetime(end_date).floor("D")]
        else:
            print("Warning: 'FECHA' column not found in dataframe. Showing all data without date filtering.")

    # 2. Data Preparation
    if 'UITI_VANO' in df.columns:
        df['UITI_VANO'] = pd.to_numeric(df['UITI_VANO'], errors='coerce').fillna(0.0)

    # Calculate metrics per circuit. Frequency counts distinct FECHA values.
    counts = count_unique_event_dates(df, "CIRCUITO") if not df.empty else pd.Series(dtype=float)
    sums = df.groupby('CIRCUITO')['UITI_VANO'].sum() if not df.empty else pd.Series(dtype=float)

    # Merge into a coordinate dataframe
    df_coords = pd.DataFrame({
        'event_count': counts,
        'uiti_vano_sum': sums
    }).dropna()

    # Handle empty dataframe edge case
    if df_coords.empty:
        df_coords['cluster'] = pd.Series(dtype=float)
        df_coords['criticidad'] = pd.Series(dtype=object)
        df_coords['centroid_distance'] = pd.Series(dtype=float)
        df_coords.index.name = "CIRCUITO"
        return df_coords[empty_columns]

    df_coords.index.name = "CIRCUITO"

    # Explicitly cast to float before converting to NumPy values. K-Means
    # clusters in the ORIGINAL (non-log) event_count/uiti_vano_sum space,
    # min-max scaled; the chart itself renders both axes log-scaled, so the
    # visualized space and the clustering space intentionally differ here.
    X_raw = df_coords[['event_count', 'uiti_vano_sum']].astype(float).values
    X = X_raw

    # 3. Scaling (Min-Max normalization to [0, 1])
    X_min = X.min(axis=0)
    X_range = X.max(axis=0) - X_min
    # Add a small epsilon to the range to avoid division by zero
    X_range = np.where(X_range == 0, 1e-9, X_range)
    X_scaled = (X - X_min) / X_range

    # Execute clustering. `run_kmeans(random_state=...)` seeds the numpy
    # GLOBAL RNG (`np.random.seed`), a process-wide side effect. Save/restore
    # the global state around the call so this function never silently
    # resets or correlates unrelated randomness for other code sharing the
    # process afterward (e.g. the simulator in report_pipeline.py).
    n_clusters = min(len(group_labels), len(df_coords))
    rng_state = np.random.get_state()
    try:
        df_coords['cluster'] = run_kmeans(X_scaled, n_clusters=n_clusters, random_state=42)
    finally:
        np.random.set_state(rng_state)

    # Rank clusters based on the mean of their scaled coordinates (higher means more critical)
    cluster_scores = {}
    for cluster_id in range(n_clusters):
        cluster_mask = df_coords['cluster'] == cluster_id
        cluster_scores[cluster_id] = X_scaled[cluster_mask].mean()

    sorted_clusters = sorted(cluster_scores.keys(), key=lambda c: cluster_scores[c], reverse=True)

    df_coords['criticidad'] = df_coords['cluster'].apply(
        lambda cluster_id: group_labels[sorted_clusters.index(cluster_id)]
    )

    # Post-hoc centroid recompute (informe-gerencial, additive): does NOT
    # change `run_kmeans`'s signature/return value. Centroids are the mean
    # of each cluster's `X_scaled` points; `centroid_distance` is each
    # circuit's Euclidean distance to its OWN cluster's centroid (most
    # representative circuits have the smallest value).
    cluster_labels = df_coords['cluster'].values
    centroids = np.array([
        X_scaled[cluster_labels == k].mean(axis=0) for k in range(n_clusters)
    ])
    df_coords['centroid_distance'] = np.linalg.norm(X_scaled - centroids[cluster_labels], axis=1)

    return df_coords[empty_columns]


def plot_interactive_circuit_clustering(
    raw_df, start_date=None, end_date=None, highlighted_circuits=None, group_labels=None, group_colors=None
):
    """
    Plots an interactive scatter map of events frequency vs UITI_VANO sums
    clustered via K-Means.

    Parameters:
    - raw_df (pd.DataFrame): The main dataset containing 'CIRCUITO', 'UITI_VANO', and 'FECHA'.
    - start_date (str, optional): Start date string (e.g. '2023-01-01').
    - end_date (str, optional): End date string.
    - highlighted_circuits (list): List of circuit names to highlight with an 'X'.
    - group_labels (sequence[str], optional): Overrides `CRITICALITY_GROUP_LABELS`;
      forwarded to `compute_circuit_criticality_groups`. All callers share the
      same 5-tier default unless explicitly overridden.
    - group_colors (sequence[str], optional): Overrides `CRITICALITY_GROUP_COLORS`;
      must be at least as long as `group_labels` when both are provided.
    """
    if highlighted_circuits is None:
        highlighted_circuits = []

    group_labels = list(group_labels) if group_labels is not None else list(CRITICALITY_GROUP_LABELS)
    group_colors = list(group_colors) if group_colors is not None else list(CRITICALITY_GROUP_COLORS)

    df_coords = compute_circuit_criticality_groups(raw_df, start_date, end_date, group_labels=group_labels)

    # Handle empty dataframe edge case
    if df_coords.empty:
        print("No data available for the given date range.")
        return go.Figure()

    # 4. Plotting Setup
    fig = go.Figure()

    # Plot clusters (Combining both normal and highlighted logic inside the same loop)
    for rank, label in enumerate(group_labels):
        cluster_data = df_coords[df_coords['criticidad'] == label]
        if cluster_data.empty:
            continue

        color = group_colors[rank]

        # Split into normal vs highlighted for this specific cluster
        normal_data = cluster_data[~cluster_data.index.isin(highlighted_circuits)]
        highlighted_data = cluster_data[cluster_data.index.isin(highlighted_circuits)]

        # We assign them to the same legendgroup so they toggle together
        legend_group_name = f'group_{rank}'
        legend_name = f'{label} (n={len(cluster_data)})'

        # 4a. Plot normal points (Circles)
        if not normal_data.empty:
            fig.add_trace(go.Scatter(
                x=normal_data['event_count'],
                y=normal_data['uiti_vano_sum'],
                mode='markers+text',
                marker=dict(
                    color=color,
                    symbol='circle',
                    size=7,
                    line=dict(color='#0f172a', width=1),
                    opacity=0.5
                ),
                text=normal_data.index,
                textposition="top right",
                textfont=dict(size=7, color="#64748b"), # Lighter slate for normal text
                name=legend_name,
                legendgroup=legend_group_name,
                showlegend=True if highlighted_data.empty else True, # Main legend toggle
                hovertemplate=f'<b>%{{text}}</b><br>Grupo: {label}<br>Eventos: %{{x:,.0f}}<br>Suma UITI_VANO: %{{y:,.2f}}<extra></extra>'
            ))

        # 4b. Plot highlighted points (Crosses 'X') retaining cluster color
        if not highlighted_data.empty:
            fig.add_trace(go.Scatter(
                x=highlighted_data['event_count'],
                y=highlighted_data['uiti_vano_sum'],
                mode='markers+text',
                marker=dict(
                    color=color,
                    symbol='x',
                    size=12,
                    line=dict(color='#0f172a', width=2),
                    opacity=1.0 # Make them fully opaque to stand out
                ),
                text=highlighted_data.index,
                textposition="top right",
                textfont=dict(size=10, color="#dc2626", weight="bold"), # Red bold text to stand out
                name=legend_name,
                legendgroup=legend_group_name,
                showlegend=False if not normal_data.empty else True, # Hide legend duplicate if normal points exist
                hovertemplate=f'<b>%{{text}}</b><br>Grupo: {label}<br>Eventos: %{{x:,.0f}}<br>Suma UITI_VANO: %{{y:,.2f}}<br><i>DESTACADO</i><extra></extra>'
            ))

    # Expand axes limits by 10%
    max_x = df_coords['event_count'].max()
    max_y = df_coords['uiti_vano_sum'].max()
    if pd.notna(max_x) and pd.notna(max_y):
        fig.add_trace(go.Scatter(
            x=[max_x * 1.1],
            y=[max_y * 1.1],
            mode='markers',
            marker=dict(color='rgba(0,0,0,0)', size=1),
            showlegend=False,
            hoverinfo='none'
        ))

    # Dynamic Title. K reflects the actual number of clusters K-Means produced
    # for this data (min(len(CRITICALITY_GROUP_LABELS), len(df_coords)) inside
    # compute_circuit_criticality_groups), not a hardcoded constant.
    n_clusters_used = df_coords['cluster'].nunique()
    title_text = f'Agrupamiento de Circuitos: Frecuencia de Eventos vs Suma de UITI_VANO (K={n_clusters_used})'
    if start_date and end_date:
        title_text += f'<br><sup>Periodo: {start_date} a {end_date}</sup>'
    elif start_date:
        title_text += f'<br><sup>Periodo: Desde {start_date}</sup>'
    elif end_date:
        title_text += f'<br><sup>Periodo: Hasta {end_date}</sup>'
    else:
        # Extract the minimum and maximum dates available dynamically from FECHA
        if 'FECHA' in raw_df.columns:
            fechas_dt = pd.to_datetime(raw_df['FECHA'], errors='coerce').dropna()
            if not fechas_dt.empty:
                min_date = fechas_dt.min()#.strftime('%Y-%m-%d')
                max_date = fechas_dt.max()#.strftime('%Y-%m-%d')
                title_text += f'<br><sup>Periodo: {min_date} a {max_date}</sup>'
            else:
                title_text += f'<br><sup>Periodo: Datos sin Fechas Válidas</sup>'
        else:
            title_text += f'<br><sup>Periodo: Datos sin Fechas</sup>'

    # Formatting axes
    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=16, family="Arial, sans-serif")
        ),
        xaxis_title='Número de Eventos por Circuito',
        yaxis_title='Suma de UITI_VANO',
        plot_bgcolor='#f8fafc',
        paper_bgcolor='#ffffff',
        xaxis=dict(
            type='log',
            showgrid=True,
            gridcolor='#e2e8f0',
            gridwidth=1,
            griddash='dot',
        ),
        yaxis=dict(
            type='log',
            showgrid=True,
            gridcolor='#e2e8f0',
            gridwidth=1,
            griddash='dot',
        ),
        legend=dict(
            title='Grupos Criticidad',
            bgcolor='rgba(255, 255, 255, 0.95)',
            bordercolor='#e2e8f0',
            borderwidth=1,
            x=0.75, # Bottom Right roughly
            y=0.02
        ),
        height=750,
        margin=dict(l=60, r=50, t=90, b=80),
        hovermode="closest"
    )

    return fig

import pandas as pd
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

    destacado = str(circuito_destacado or "")
    posiciones = list(range(len(tabla)))
    valores = tabla["vanos_criticos"].tolist()
    es_destacado = [c == destacado for c in tabla["circuito"]]

    hover = [
        f"<b>{fila.circuito}</b>"
        f"<br>Medio-Alto + Alto: <b>{fila.vanos_criticos}</b>"
        f"<br>  Medio-Alto: {fila.vanos_medio_alto}"
        f"<br>  Alto: {fila.vanos_alto}"
        f"<br>De {fila.vanos_con_eventos} vanos con eventos"
        f"<br>UITI acumulado: <b>{fila.uiti_total:,.1f}</b>"
        f"<br>Eventos (suma por vano): <b>{fila.eventos_total:,}</b>"
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
    if any(es_destacado):
        fila = tabla[tabla["circuito"] == destacado].iloc[0]
        encabezado = (
            f"Ranking de circuitos por vanos criticos &mdash; {destacado}: "
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
            text=(f"{encabezado}<br><sup>{reparto} &mdash; sin eventos: "
                  f"{resultado.circuitos_sin_eventos} | en cero (sin vanos Medio-Alto "
                  f"ni Alto): {resultado.circuitos_en_cero} &mdash; {periodo}</sup>"),
            font=dict(size=16, family="Arial, sans-serif"),
        ),
        # Nombres como ticks sobre un eje NUMERICO: ver el comentario de las divisiones.
        xaxis=dict(
            type="linear",
            tickvals=posiciones,
            ticktext=tabla["circuito"].tolist(),
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


def _load_geo_vanos_for_circuit(circuito_name: str):
    geo_path = PROJECT_ROOT / "data" / "GEO" / "MVLINSEC.shp"
    if not geo_path.exists():
        return None

    try:
        import geopandas as gpd
    except ImportError:
        return None

    lineas = gpd.read_file(geo_path)
    required_cols = {"CIRCUITO", "G3E_FID", "geometry"}
    if not required_cols.issubset(lineas.columns):
        return None

    geo = lineas[lineas["CIRCUITO"].astype(str).eq(str(circuito_name))].copy()
    if geo.empty:
        return None

    geo["FID_VANO_GEO"] = _norm_map_id(geo["G3E_FID"])
    return geo


def _load_geo_points_for_circuit(circuito_name: str, filename: str, fid_column: str):
    geo_path = PROJECT_ROOT / "data" / "GEO" / filename
    if not geo_path.exists():
        return None

    try:
        import geopandas as gpd
    except ImportError:
        return None

    points = gpd.read_file(geo_path)
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
            geo_plot[metric_class_column] = geo_plot["metric_class"].fillna("Sin clase")
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
    # El semaforo de criticidad de los cuadernos: los cuatro grupos que devuelve
    # `asignar_clase` (0=Bajo..3=Alto). `Muy alto` se conserva por los caminos antiguos
    # que rotulaban con esa cuarta palabra; sin `Medio-Alto` los vanos de ese grupo
    # caian a "Sin clase" y el mapa los pintaba de gris sin decir por que.
    class_colors = {
        "Bajo": "#1a9641",
        "Medio": "#f2c200",
        "Medio-Alto": "#ef6c00",
        "Alto": "#c62828",
        "Muy alto": "#c62828",
    }

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
            rgba = mapper.to_rgba(min(float(value or 0), vmax_robust), bytes=True)
            return {"color": f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}", "weight": grosor,
                    "opacity": 1.0 if resaltado else 0.85}
        return {"color": "#9ca3af", "weight": 2, "opacity": 0.45}

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
            legend_items = "".join(
                f"<div><span style='display:inline-block;width:11px;height:11px;background:{color};"
                f"margin-right:6px;border-radius:2px;'></span>{label}</div>"
                for label, color in class_colors.items()
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
                    body.append(f"<li>{_escape(text)}{details}</li>")
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
                    f"<td>{_escape(item.get('variable'))}</td>"
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
        f"<ul class='report-list'><li>{_escape(synthesis)}</li></ul>"
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

    html_clusters = fig_ranking.to_html(full_html=False, include_plotlyjs='cdn') if fig_ranking else ""

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

    def _text_to_items(text: str, *, max_items: int | None = None) -> str:
        """Split a prose paragraph into <ul><li> items of at most ~2 visual lines."""
        import re as _re
        raw = ("" if text is None else str(text)).strip()
        if not raw:
            return ""
        # Split on sentence-terminating punctuation followed by whitespace.
        sentences = [s.strip() for s in _re.split(r'(?<=[.!?;])\s+', raw) if s.strip()]
        if not sentences:
            return f"<ul class='report-list'><li>{_escape(raw)}</li></ul>"
        MAX_CHARS = 150  # ~2 lines at 700 px container width
        items, current, cur_len = [], [], 0
        for s in sentences:
            if current and cur_len + len(s) + 1 > MAX_CHARS:
                items.append(" ".join(current))
                current, cur_len = [s], len(s)
            else:
                current.append(s)
                cur_len += len(s) + 1
        if current:
            items.append(" ".join(current))
        if max_items is not None:
            items = items[:max_items]
        lis = "".join(f"<li>{_escape(item)}</li>" for item in items)
        return f"<ul class='report-list'>{lis}</ul>"

    def _list_to_items(items, *, max_items: int | None = None) -> str:
        clean_items = [str(item).strip() for item in (items or []) if str(item).strip()]
        if max_items is not None:
            clean_items = clean_items[:max_items]
        if not clean_items:
            return ""
        lis = "".join(f"<li>{_escape(item)}</li>" for item in clean_items)
        return f"<ul class='report-list'>{lis}</ul>"

    def _figure_html(fig, title=None, show_title=False):
        if not fig:
            return ""
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
                f"{_iframe_srcdoc(dibujado.get_root().render(), height=560)}</div>"
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
        control = ""
        if len(capas) > 1:
            marcas = "".join(
                f"<span class='marca-estudiada' style='flex:1;text-align:center;'>{e}</span>"
                if estudiada else
                f"<span style='flex:1;text-align:center;'>{e}</span>"
                for e, estudiada in etiquetas)
            control = (
                "<div class='mapa-control'>"
                f"<input type='range' min='0' max='{len(capas) - 1}' value='0' step='1' "
                "class='mapa-deslizador' aria-label='Ventana del mapa'>"
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
        return (f"<h3>Estado del circuito en las ventanas estudiadas</h3>"
                f"<div class='visor-mapas'>{control}{''.join(capas)}</div>"
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
        grupos = ("Bajo", "Medio", "Medio-Alto", "Alto")

        def _grupo(indice):
            try:
                return grupos[int(indice)]
            except (TypeError, ValueError, IndexError):
                return "N/D"

        filas = []
        for vano in sorted(vanos, key=lambda v: -float(v.get("u_base") or 0.0))[:15]:
            delta = int(vano.get("delta_grupo") or 0)
            marca = "&#9660;" if delta < 0 else ("&#9650;" if delta > 0 else "&mdash;")
            filas.append(
                "<tr>"
                f"<td style='text-align:left;'>{_escape(vano.get('fid'))}</td>"
                f"<td>{float(vano.get('u_base') or 0.0):,.1f}</td>"
                f"<td>{float(vano.get('u_simulado') or 0.0):,.1f}</td>"
                f"<td>{_escape(_grupo(vano.get('clase_base')))}</td>"
                f"<td>{_escape(_grupo(vano.get('clase_simulada')))} {marca}</td>"
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
            "<thead><tr><th>Vano</th><th>UITI medido</th>"
            "<th>UITI simulado</th><th>Grupo actual</th><th>Grupo simulado</th>"
            "<th>Pasos</th></tr></thead>"
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
                _chart_panel(f"Qué variables se mueven juntas &mdash; {titulo}", html_grafo),
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
                "<div class='summary-box'><h3 style='margin-top:0;'>Sintesis del modelo "
                "sobre las ventanas estudiadas</h3>"
                + _list_to_items(hallazgos, max_items=5) + "</div>")

        return "\n".join(cabecera), (
            "<h2>Diagnóstico y simulación por ventana</h2>" + "\n".join(secciones))


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
        if stage_breakdown:
            # Per-stage breakdown (design #327 ADR-2): one row per agent
            # stage (historical/inference/expert-alignment)
            # from `report_pipeline._resolve_stage_breakdown`. Additive --
            # placed AFTER the whole-run tokens_total/elapsed_seconds block
            # above, never replacing it. Reuses the SAME
            # measured/mixed/estimated label convention as that block, via
            # `_token_source_label` (extracted above `render_llm_analysis`
            # since this is now the third occurrence of the same mapping).
            rows_html = []
            for entry in stage_breakdown:
                stage_token_source = entry.get("token_source", "estimated")
                stage_label, stage_prefix = _token_source_label(stage_token_source)
                stage_tokens_total = entry.get("tokens_total")
                if stage_tokens_total is not None:
                    tok_cell = f"{stage_prefix}{stage_tokens_total:,} ({stage_label})"
                else:
                    tok_cell = "N/D"
                stage_duration = entry.get("duration_seconds")
                if stage_duration is not None:
                    dur_cell = f"{_format_elapsed_seconds(stage_duration)} (medidos)"
                else:
                    dur_cell = "N/D"
                rows_html.append(
                    "<tr>"
                    f"<td style='text-align:left;'>{entry.get('stage', '')}</td>"
                    f"<td>{tok_cell}</td>"
                    f"<td>{dur_cell}</td>"
                    "</tr>"
                )
            subtitle_info += (
                "<br><span style='font-size: 0.8em; color: #94a3b8;'>"
                "Desglose por etapa (agente):"
                "<table style='display:inline-table; font-size:0.95em; border-collapse:collapse;'>"
                "<tr><th style='text-align:left;'>Etapa</th><th>Tokens</th><th>Tiempo</th></tr>"
                f"{''.join(rows_html)}"
                "</table></span>"
            )
    else:
        subtitle_info = f"Período de análisis: {period_str} | (Solo visualización, sin análisis LLM)"

    # Los dos logos viajan DENTRO del HTML como `data:` URI. El informe se abre desde
    # cualquier carpeta del disco y se manda por correo: un `<img src="site/...">`
    # daria un icono roto en cuanto el archivo cambie de sitio. Si el PNG falta, no se
    # dibuja nada -- un informe no se pierde por un adorno.
    _dir_logos = PROJECT_ROOT / "site" / "assets" / "site" / "logos"

    def _logo_html(nombre_archivo, clase, alt):
        ruta = _dir_logos / nombre_archivo
        if not ruta.is_file():
            return ""
        import base64 as _b64

        dato = _b64.b64encode(ruta.read_bytes()).decode("ascii")
        return (f"<img class='{clase}' alt='{_escape(alt)}' "
                f"src='data:image/png;base64,{dato}'>")

    # Arriba a la derecha, el escudo de quien OPERA la red: es el destinatario.
    escudo_html = _logo_html("checlogo.png", "escudo-chec", "CHEC Grupo EPM")
    # Abajo a la derecha, junto al texto, el logo de quien PRODUJO el informe. Separado
    # del escudo a proposito: juntos arriba se leerian como dos marcas del mismo emisor.
    logo_labia_html = _logo_html("logo_labIA.png", "logo-labia",
                                 "Laboratorio de Inteligencia Artificial")

    title_html = f"Reporte Criticidad - Circuito: {primary_circuit}<br><span style='font-size: 0.6em; color: #64748b;'>{subtitle_info}</span>"

    html_maps_section = _mapas_ventana_html()

    html_inference_characterization, html_inference_critical = _render_inference_layout(inference_results, inference_analysis)
    characterization_visuals_html = f"{html_maps_section}{html_inference_characterization}"
    html_expert_alignment = render_expert_alignment_tab(expert_alignment_analysis)

    llm_sections_html = ""
    if validation_data:
        exec_summary = validation_data.get('executive_summary', [])
        if isinstance(exec_summary, list):
            exec_summary = " ".join(exec_summary)

        # Parse circuit characterization
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
            ventanas_narradas = char_data.get('ventanas_estudiadas', [])
            if ventanas_narradas:
                char_html += (
                    "<h4>Ventanas estudiadas</h4>"
                    + _list_to_items([str(v) for v in ventanas_narradas]))

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
                        char_html += f"<li style='margin-bottom: 8px;'><strong>Modo {modo} ({vars_assoc}):</strong> {just_fis}<br><span style='font-size: 0.95em; color: #475569;'><em>Análisis:</em> {ana}</span></li>"
                    else:
                        char_html += f"<li>{j}</li>"
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

        findings_html = ""
        if findings_texts:
            findings_html += (
                "<div class='summary-box'><h3 style='margin-top:0;'>Hallazgos del análisis descriptivo</h3>"
                + _text_to_items(" ".join(findings_texts))
                + "</div>"
            )

        inferencias = (inference_analysis or {}).get('inferencias_predictivas', [])
        if inferencias:
            findings_html += "<div class='summary-box'><h4>Inferencias complementarias del modelo</h4><ul class='report-list'>"
            for inf in inferencias:
                r = inf.get('riesgo', '')
                h = inf.get('horizonte', '')
                j = inf.get('justificacion_modelo', '')
                findings_html += f"<li><b>{_escape(h)}:</b> {_escape(r)} &mdash; <i>{_escape(j)}</i></li>"
            findings_html += "</ul></div>"

        llm_sections_html = f"""
            <div class="summary-box">
                <h2 style="margin-top: 0;">Resumen Ejecutivo</h2>
                {_text_to_items(exec_summary)}
            </div>
            {findings_html}
            <div class="summary-box" style="background: #fffbeb; border-left: 5px solid #fbbf24;">
                <h2 style="margin-top: 0; color: #b45309;">Posible Causa Raíz (Hipótesis)</h2>
                {_text_to_items(hypothesis)}
            </div>

            <h2>📌 Caracterización del Circuito</h2>
            <div class="content-box">
                {char_html}
            </div>
            {characterization_visuals_html}
        """

        synthesis = validation_data.get('period_synthesis', '')
        if synthesis:
            llm_sections_html += f"""
            <h2>⏱️ Síntesis del Período</h2>
            <div class="content-box">
                {_text_to_items(synthesis)}
            </div>
            """
    elif characterization_visuals_html:
        llm_sections_html = f"""
            <h2>📌 Caracterización del Circuito</h2>
            {characterization_visuals_html}
        """

    # Aqui iba la grafica diaria de puntos criticos. Se fue con la deteccion: era la
    # unica pieza del informe que hablaba de DIAS, una rejilla que ni el ranking del 02 ni
    # el diagnostico del 06 comparten. La serie por ventana de cada escenario ocupa su
    # sitio, y esa si esta en la unidad del resto del informe.
    report_tab_html = f"""
            <div class="chart-container">{html_clusters}</div>

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
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f8fafc; color: #334155; margin: 0; padding: 20px; }}
            .container {{ position: relative; max-width: 1200px; margin: auto; padding: 25px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
            h1 {{ color: #0f172a; border-bottom: 3px solid #2563eb; padding-bottom: 10px; }}
            h2 {{ color: #1e3a8a; margin-top: 30px; }}
            h3 {{ color: #1e40af; margin-top: 18px; margin-bottom: 8px; font-size: 1rem; }}
            h4 {{ color: #334155; margin-bottom: 5px; margin-top: 15px; }}
            .summary-box {{ background: #eff6ff; padding: 15px 18px; border-left: 5px solid #3b82f6; border-radius: 6px; margin-bottom: 20px; }}
            .content-box {{ background: #ffffff; padding: 15px 18px; border: 1px solid #cbd5e1; border-radius: 6px; margin-bottom: 20px; }}
            ul.report-list {{ margin: 6px 0 4px 0; padding-left: 20px; list-style: disc; }}
            ul.report-list li {{ margin-bottom: 5px; line-height: 1.55; font-size: 0.95rem; }}
            ul {{ margin: 6px 0 4px 0; padding-left: 20px; }}
            li {{ margin-bottom: 5px; line-height: 1.55; }}
            .chart-container {{ margin-bottom: 40px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
            .chart-grid {{ display: grid; gap: 18px; margin-bottom: 28px; }}
            .chart-grid.two-col {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
            .chart-panel {{ border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; background: #ffffff; min-width: 0; }}
            .chart-panel h3 {{ margin: 0; padding: 10px 14px; background: #f8fafc; color: #1e3a8a; font-size: 15px; border-bottom: 1px solid #e2e8f0; }}
            .embedded-figure {{ display: block; width: 100%; height: auto; padding: 12px; box-sizing: border-box; }}
            /* El anillo del grafo, a la mitad y centrado. Cuadrado a ancho completo
               ocupa tanto alto como ancho y desplaza al resto de la seccion. */
            .figura-mitad .embedded-figure {{ width: 50%; margin: 0 auto; }}
            /* El escudo, fijo arriba a la derecha de cada pagina del informe. */
            .escudo-chec {{ position: absolute; top: 18px; right: 22px; height: 54px;
                            width: auto; }}
            /* El pie alinea el texto y el logo del laboratorio a la DERECHA, sobre la
               misma linea de base: el logo firma la frase, no la encabeza. */
            .pie-agentes {{ display: flex; align-items: center; justify-content: flex-end;
                            gap: 12px; color: #64748b; font-size: 12px;
                            padding: 14px 22px 8px 0; border-top: 1px solid #e2e8f0;
                            margin-top: 26px; }}
            .logo-labia {{ height: 34px; width: auto; }}
            /* UN visor de mapa: las capas se apilan en el mismo sitio y el deslizador
               elige cual se ve. Tres mapas seguidos obligan a bajar y subir, y a esa
               distancia la comparacion se hace de memoria. */
            .visor-mapas {{ border: 1px solid #e2e8f0; border-radius: 8px;
                            background: #ffffff; padding: 12px; }}
            .mapa-ventana {{ display: none; }}
            .mapa-ventana.activa {{ display: block; }}
            .mapa-control {{ margin: 0 0 12px 0; }}
            .mapa-deslizador {{ width: 100%; accent-color: #2563eb; }}
            .mapa-marcas {{ display: flex; color: #64748b; font-size: 12px;
                            margin-top: 2px; }}
            /* Las tres ventanas que el informe estudia, entre las once del deslizador:
               son las unicas con escenario, diagnostico y plan detras. */
            .marca-estudiada {{ color: #1e3a8a; font-weight: 700; }}
            .graph-panel iframe {{ width: 100%; height: 620px; border: 0; background: #ffffff; }}
            .graph-actions {{ padding: 10px 14px; border-bottom: 1px solid #e2e8f0; background: #ffffff; }}
            .graph-actions a {{ color: #1d4ed8; font-weight: 600; text-decoration: none; }}
            .table-scroll {{ overflow-x: auto; }}
            .compact-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
            .compact-table th, .compact-table td {{ border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; vertical-align: top; }}
            .compact-table th {{ background: #f8fafc; color: #1e3a8a; }}
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
            <div class="pie-agentes"><span>Reporte construido por agentes de IA</span>{logo_labia_html}</div>
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
                    var deslizador = visor.querySelector('.mapa-deslizador');
                    if (!deslizador) {{ return; }}
                    var capas = visor.querySelectorAll('.mapa-ventana');
                    var marcas = visor.querySelectorAll('.mapa-marcas span');
                    function mostrar() {{
                        var i = parseInt(deslizador.value, 10);
                        capas.forEach(function(capa, k) {{
                            capa.classList.toggle('activa', k === i);
                        }});
                        marcas.forEach(function(marca, k) {{
                            marca.style.fontWeight = (k === i) ? '700' : '400';
                            marca.style.color = (k === i) ? '#1e3a8a' : '#64748b';
                        }});
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
