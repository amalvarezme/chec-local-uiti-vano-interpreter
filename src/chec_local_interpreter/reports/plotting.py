from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from chec_local_interpreter.config import PROJECT_ROOT
from chec_local_interpreter.data.event_counts import count_unique_event_dates


def save_uiti_vano_plot(
    daily_df: pd.DataFrame,
    critical_points: list[dict[str, object]],
    *,
    selected_circuitos: list[str],
    start_date: str | None,
    end_date: str | None,
    output_path: str | Path,
) -> Path:
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "chec_local_matplotlib"))
    import matplotlib.pyplot as plt

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 5))
    if not daily_df.empty:
        work = daily_df.copy()
        work["fecha_dia"] = pd.to_datetime(work["fecha_dia"], errors="coerce")
        ax.plot(work["fecha_dia"], work["UITI_VANO"], color="#19535F", linewidth=1.8, label="UITI_VANO diario")
        point_dates = [pd.to_datetime(point["fecha_dia"]) for point in critical_points]
        if point_dates:
            point_frame = work[work["fecha_dia"].isin(point_dates)]
            ax.scatter(
                point_frame["fecha_dia"],
                point_frame["UITI_VANO"],
                color="#D1495B",
                s=55,
                zorder=3,
                label="Puntos criticos",
            )
    circuit_text = ", ".join(selected_circuitos[:4]) if selected_circuitos else "todos los circuitos"
    if len(selected_circuitos) > 4:
        circuit_text += f" +{len(selected_circuitos) - 4}"
    ax.set_title(f"UITI_VANO - {circuit_text} - {start_date or 'inicio'} a {end_date or 'fin'}")
    ax.set_xlabel("Fecha")
    ax.set_ylabel("UITI_VANO")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(target, dpi=150)
    plt.close(fig)
    return target


import numpy as np
import plotly.graph_objects as go
import plotly.express as px

import numpy as np
import pandas as pd
import plotly.graph_objects as go

def plot_interactive_circuit_events(raw_df, start_date=None, end_date=None):
    """
    Plots an interactive bar chart of events per circuit with quartile backgrounds.

    Parameters:
    - raw_df (pd.DataFrame): The main dataset containing 'CIRCUITO' and optionally 'FECHA' columns.
    - start_date (str, optional): The start date to filter the data (e.g., '2023-01-01').
    - end_date (str, optional): The end date to filter the data.

    Returns:
    - fig: A plotly Figure object.
    """
    df = raw_df.copy()

    # Check if we need to filter by date and ensure FECHA is parsed safely
    if start_date is not None or end_date is not None:
        if 'FECHA' in df.columns:
            # Parse FECHA as per project rules
            if not pd.api.types.is_datetime64_any_dtype(df['FECHA']):
                df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')

            if start_date is not None:
                df = df[df['FECHA'] >= pd.to_datetime(start_date)]
            if end_date is not None:
                df = df[df['FECHA'] <= pd.to_datetime(end_date)]
        else:
            print("Warning: 'FECHA' column not found in dataframe. Showing all data without date filtering.")

    # 1. Calculate events per circuit as distinct FECHA values, not raw rows.
    circuit_counts = count_unique_event_dates(df, "CIRCUITO").sort_values(ascending=False)

    # Handle empty dataframe edge case (e.g. if dates are too narrow)
    if circuit_counts.empty:
        print("No data available for the given date range.")
        return go.Figure()

    # 2. Compute the quartile boundaries
    q1 = circuit_counts.quantile(0.25)
    q2 = circuit_counts.quantile(0.50)  # Median
    q3 = circuit_counts.quantile(0.75)
    min_val = circuit_counts.min()
    max_val = circuit_counts.max()

    # 3. Create the plot
    fig = go.Figure()

    # High-aesthetic canvas styles (slate-themed colors)
    colors = ['#f1f5f9', '#eff6ff', '#ecfdf5', '#fff1f2']  # Slate, Blue, Emerald, Rose

    # Plot the bars for all circuits
    fig.add_trace(go.Bar(
        x=circuit_counts.index,
        y=circuit_counts.values,
        marker_color='rgba(37, 99, 235, 0.6)',  # Blue with some transparency
        name='Eventos',
        showlegend=False
    ))

    # 4. Add horizontal background quartile spans using shapes
    fig.add_hrect(y0=0, y1=q1, fillcolor=colors[0], opacity=1, layer="below", line_width=0)
    fig.add_hrect(y0=q1, y1=q2, fillcolor=colors[1], opacity=1, layer="below", line_width=0)
    fig.add_hrect(y0=q2, y1=q3, fillcolor=colors[2], opacity=1, layer="below", line_width=0)
    fig.add_hrect(y0=q3, y1=max_val * 1.05, fillcolor=colors[3], opacity=1, layer="below", line_width=0)

    # Dummy traces to replicate the matplotlib quartile background legend
    legend_labels = [
        f'Q1 (0-25%): 0 - {q1:.1f} eventos',
        f'Q2 (25-50%): {q1:.1f} - {q2:.1f} eventos',
        f'Q3 (50-75%): {q2:.1f} - {q3:.1f} eventos',
        f'Q4 (75-100%): {q3:.1f} - {max_val} eventos'
    ]

    for i in range(4):
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='markers',
            marker=dict(size=12, color=colors[i], symbol='square', line=dict(color='#cbd5e1', width=1)),
            name=legend_labels[i]
        ))

    # 5. Draw dashed boundary lines for quartile cuts
    fig.add_hline(y=q1, line_dash="dash", line_color="#2563eb", line_width=1.5,
                  annotation_text=f'<b>Q1 ({q1:.1f})</b>', annotation_position="top left", annotation_font_color="#1d4ed8")
    fig.add_hline(y=q2, line_dash="dash", line_color="#059669", line_width=1.5,
                  annotation_text=f'<b>Q2/Med ({q2:.1f})</b>', annotation_position="top left", annotation_font_color="#047857")
    fig.add_hline(y=q3, line_dash="dash", line_color="#e11d48", line_width=1.5,
                  annotation_text=f'<b>Q3 ({q3:.1f})</b>', annotation_position="top left", annotation_font_color="#be123c")

    # Dynamic Title indicating date range
    title_text = 'Eventos por Circuito Ordenados por Frecuencia con Cuartiles en Fondo'
    if start_date and end_date:
        title_text += f'<br><sup>Periodo: {start_date} a {end_date}</sup>'
    elif start_date:
        title_text += f'<br><sup>Periodo: Desde {start_date}</sup>'
    elif end_date:
        title_text += f'<br><sup>Periodo: Hasta {end_date}</sup>'
    else:
        title_text += f'<br><sup>Periodo: {pd.to_datetime(raw_df["FECHA"]).min()} a {pd.to_datetime(raw_df["FECHA"]).max()}</sup>'

    # 6. Formatting
    max_circuits = 300
    xaxis_range = [-0.5, min(len(circuit_counts) - 0.5, max_circuits - 0.5)]

    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=18, family="Arial, sans-serif")
        ),
        xaxis_title='Circuitos (Ordenados por frecuencia)',
        yaxis_title='Número de Eventos',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='#ffffff',
        xaxis=dict(
            tickangle=-90,
            range=xaxis_range,
            showgrid=False
        ),
        yaxis=dict(
            range=[0, max_val * 1.05],
            showgrid=True,
            gridcolor='#e2e8f0',
            gridwidth=1,
            griddash='dot'
        ),
        legend=dict(
            title='Rango de Cuartiles (Fondo)',
            bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor='#e2e8f0',
            borderwidth=1,
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=0.99
        ),
        height=650,
        margin=dict(l=60, r=50, t=90, b=150),
        hovermode="x unified"
    )

    return fig

from pandas.core.arrays import string_arrow
import numpy as np
import pandas as pd
import plotly.graph_objects as go

def plot_interactive_uiti_vano_sums(raw_df, start_date=None, end_date=None):
    """
    Plots an interactive bar chart of the sum of UITI_VANO per circuit with quartile backgrounds.

    Parameters:
    - raw_df (pd.DataFrame): The main dataset containing 'CIRCUITO', 'UITI_VANO', and optionally 'FECHA'.
    - start_date (str, optional): The start date to filter the data (e.g., '2023-01-01').
    - end_date (str, optional): The end date to filter the data.

    Returns:
    - fig: A plotly Figure object.
    """
    df = raw_df.copy()

    # 1. Ensure UITI_VANO is numeric and handle missing values
    df['UITI_VANO'] = pd.to_numeric(df['UITI_VANO'], errors='coerce').fillna(0.0)

    # 2. Check if we need to filter by date and ensure FECHA is parsed safely
    if start_date is not None or end_date is not None:
        if 'FECHA' in df.columns:
            # Parse FECHA as per project rules
            if not pd.api.types.is_datetime64_any_dtype(df['FECHA']):
                df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')

            if start_date is not None:
                df = df[df['FECHA'] >= pd.to_datetime(start_date)]
            if end_date is not None:
                df = df[df['FECHA'] <= pd.to_datetime(end_date)]
        else:
            print("Warning: 'FECHA' column not found in dataframe. Showing all data without date filtering.")

    # Deduplicar por FECHA y FID_VANO si existen para evitar sobreconteo por múltiples equipos
    # if 'FECHA' in df.columns and 'FID_VANO' in df.columns:
    #     if not pd.api.types.is_datetime64_any_dtype(df['FECHA']):
    #         df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
    #     df = df.drop_duplicates(subset=['FECHA', 'FID_VANO'])

    # 3. Group by circuit and calculate total UITI_VANO (sorted descending)
    circuit_sums = df.groupby('CIRCUITO')['UITI_VANO'].sum().sort_values(ascending=False)

    # Handle empty dataframe edge case
    if circuit_sums.empty:
        print("No data available for the given date range.")
        return go.Figure()

    # 4. Compute quartile boundaries for the sums
    q1 = circuit_sums.quantile(0.25)
    q2 = circuit_sums.quantile(0.50)  # Median
    q3 = circuit_sums.quantile(0.75)
    min_val = circuit_sums.min()
    max_val = circuit_sums.max()

    # 5. Create the plot
    fig = go.Figure()

    # High-aesthetic canvas styles (slate-themed colors)
    colors = ['#f1f5f9', '#eff6ff', '#ecfdf5', '#fff1f2']  # Slate, Blue, Emerald, Rose

    # Plot the bars for all circuits
    fig.add_trace(go.Bar(
        x=circuit_sums.index,
        y=circuit_sums.values,
        marker_color='rgba(37, 99, 235, 0.6)',  # Blue with some transparency
        name='Suma UITI_VANO',
        showlegend=False,
        hovertemplate='%{x}<br>Suma: %{y:,.0f}<extra></extra>' # Add thousands separator to hover
    ))

    # 6. Add horizontal background quartile spans using shapes
    fig.add_hrect(y0=0, y1=q1, fillcolor=colors[0], opacity=1, layer="below", line_width=0)
    fig.add_hrect(y0=q1, y1=q2, fillcolor=colors[1], opacity=1, layer="below", line_width=0)
    fig.add_hrect(y0=q2, y1=q3, fillcolor=colors[2], opacity=1, layer="below", line_width=0)
    fig.add_hrect(y0=q3, y1=max_val * 1.05, fillcolor=colors[3], opacity=1, layer="below", line_width=0)

    # Dummy traces to replicate the matplotlib quartile background legend
    legend_labels = [
        f'Q1 (0-25%): 0 - {q1:,.0f}',
        f'Q2 (25-50%): {q1:,.0f} - {q2:,.0f}',
        f'Q3 (50-75%): {q2:,.0f} - {q3:,.0f}',
        f'Q4 (75-100%): {q3:,.0f} - {max_val:,.0f}'
    ]

    for i in range(4):
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode='markers',
            marker=dict(size=12, color=colors[i], symbol='square', line=dict(color='#cbd5e1', width=1)),
            name=legend_labels[i]
        ))

    # 7. Draw dashed boundary lines for quartile cuts
    fig.add_hline(y=q1, line_dash="dash", line_color="#2563eb", line_width=1.5,
                  annotation_text=f'<b>Q1 ({q1:,.0f})</b>', annotation_position="top left", annotation_font_color="#1d4ed8")
    fig.add_hline(y=q2, line_dash="dash", line_color="#059669", line_width=1.5,
                  annotation_text=f'<b>Q2/Med ({q2:,.0f})</b>', annotation_position="top left", annotation_font_color="#047857")
    fig.add_hline(y=q3, line_dash="dash", line_color="#e11d48", line_width=1.5,
                  annotation_text=f'<b>Q3 ({q3:,.0f})</b>', annotation_position="top left", annotation_font_color="#be123c")

    # Dynamic Title indicating date range
    title_text = 'Suma de UITI_VANO por Circuito Ordenado por Frecuencia con Cuartiles en Fondo'
    if start_date and end_date:
        title_text += f'<br><sup>Periodo: {start_date} a {end_date}</sup>'
    elif start_date:
        title_text += f'<br><sup>Periodo: Desde {start_date}</sup>'
    elif end_date:
        title_text += f'<br><sup>Periodo: Hasta {end_date}</sup>'
    else:
        title_text += f'<br><sup>Periodo: {pd.to_datetime(raw_df["FECHA"]).min()} a {pd.to_datetime(raw_df["FECHA"]).max()}</sup>'

    # 8. Formatting
    max_circuits = 350
    xaxis_range = [-0.5, min(len(circuit_sums) - 0.5, max_circuits - 0.5)]

    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=18, family="Arial, sans-serif")
        ),
        xaxis_title='Circuitos (Ordenados por suma de UITI_VANO)',
        yaxis_title='Suma de UITI_VANO',
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='#ffffff',
        xaxis=dict(
            tickangle=-90,
            range=xaxis_range,
            showgrid=False
        ),
        yaxis=dict(
            range=[0, max_val * 1.05],
            showgrid=True,
            gridcolor='#e2e8f0',
            gridwidth=1,
            griddash='dot',
            tickformat=",.0f"  # Format Y-axis values with commas as thousand separators
        ),
        legend=dict(
            title='Rango de Cuartiles (Fondo)',
            bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor='#e2e8f0',
            borderwidth=1,
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=0.99
        ),
        height=650,
        margin=dict(l=60, r=50, t=90, b=150),
        hovermode="x unified"
    )

    return fig

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

def plot_interactive_circuit_clustering(raw_df, start_date=None, end_date=None, highlighted_circuits=None):
    """
    Plots an interactive log-log scatter map of events frequency vs UITI_VANO sums
    clustered via K-Means.

    Parameters:
    - raw_df (pd.DataFrame): The main dataset containing 'CIRCUITO', 'UITI_VANO', and 'FECHA'.
    - start_date (str, optional): Start date string (e.g. '2023-01-01').
    - end_date (str, optional): End date string.
    - highlighted_circuits (list): List of circuit names to highlight with an 'X'.
    """
    if highlighted_circuits is None:
        highlighted_circuits = []

    df = raw_df.copy()

    # 1. Check if we need to filter by date and ensure FECHA is parsed safely
    if start_date is not None or end_date is not None:
        if 'FECHA' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['FECHA']):
                df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')

            if start_date is not None:
                df = df[df['FECHA'] >= pd.to_datetime(start_date)]
            if end_date is not None:
                df = df[df['FECHA'] <= pd.to_datetime(end_date)]
        else:
            print("Warning: 'FECHA' column not found in dataframe. Showing all data without date filtering.")

    # 2. Data Preparation
    df['UITI_VANO'] = pd.to_numeric(df['UITI_VANO'], errors='coerce').fillna(0.0)

    # Calculate metrics per circuit. Frequency counts distinct FECHA values.
    counts = count_unique_event_dates(df, "CIRCUITO")
    sums = df.groupby('CIRCUITO')['UITI_VANO'].sum()

    # Merge into a coordinate dataframe
    df_coords = pd.DataFrame({
        'event_count': counts,
        'uiti_vano_sum': sums
    }).dropna()

    # Handle empty dataframe edge case
    if df_coords.empty:
        print("No data available for the given date range.")
        return go.Figure()

    # Explicitly cast to float before converting to NumPy values
    X = df_coords[['event_count', 'uiti_vano_sum']].astype(float).values

    # 3. Scaling (Z-score normalization)
    X_mean = X.mean(axis=0)
    # Add a small epsilon to standard deviation to avoid division by zero
    X_std = np.where(X.std(axis=0) == 0, 1e-9, X.std(axis=0))
    X_scaled = (X - X_mean) / X_std

    # Execute clustering
    n_clusters = min(4, len(df_coords))
    df_coords['cluster'] = run_kmeans(X_scaled, n_clusters=n_clusters, random_state=42)

    # Rank clusters based on the mean of their scaled coordinates (higher means more critical)
    cluster_scores = {}
    for cluster_id in range(n_clusters):
        cluster_mask = df_coords['cluster'] == cluster_id
        cluster_scores[cluster_id] = X_scaled[cluster_mask].mean()

    sorted_clusters = sorted(cluster_scores.keys(), key=lambda c: cluster_scores[c], reverse=True)
    group_labels = ["Muy Alta", "Alta", "Media", "Baja"]
    group_colors = ["#ef4444", "#f97316", "#eab308", "#22c55e"] # Red, Orange, Yellow, Green

    # 4. Plotting Setup
    fig = go.Figure()

    # Plot clusters (Combining both normal and highlighted logic inside the same loop)
    for rank, cluster_id in enumerate(sorted_clusters):
        cluster_data = df_coords[df_coords['cluster'] == cluster_id]
        if cluster_data.empty:
            continue

        label = group_labels[rank]
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
                hovertemplate='<b>%{text}</b><br>Eventos: %{x:,.0f}<br>Suma UITI_VANO: %{y:,.0f}<extra></extra>'
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
                hovertemplate='<b>%{text}</b><br>Eventos: %{x:,.0f}<br>Suma UITI_VANO: %{y:,.0f}<br><i>DESTACADO</i><extra></extra>'
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

    # Dynamic Title
    title_text = 'Agrupamiento de Circuitos: Frecuencia de Eventos vs Suma de UITI_VANO (K=4)'
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
        xaxis_type="log", # Set Log Scale
        yaxis_type="log", # Set Log Scale
        plot_bgcolor='#f8fafc',
        paper_bgcolor='#ffffff',
        xaxis=dict(
            showgrid=True,
            gridcolor='#e2e8f0',
            gridwidth=1,
            griddash='dot',
            dtick=1,
            exponentformat='power',
            showexponent='all',
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='#e2e8f0',
            gridwidth=1,
            griddash='dot',
            dtick=1,
            exponentformat='power',
            showexponent='all',
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
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "chec_local_matplotlib"))
import matplotlib.colors as mcolors
import matplotlib.cm as cm

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


def _iter_line_xy(geometry):
    if geometry is None or geometry.is_empty:
        return
    geom_type = geometry.geom_type
    if geom_type == "LineString":
        xs, ys = geometry.xy
        yield list(xs), list(ys)
    elif geom_type == "MultiLineString":
        for part in geometry.geoms:
            xs, ys = part.xy
            yield list(xs), list(ys)


def _format_geo_value(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def _point_hover_text(row, fields: list[tuple[str, str]], title: str) -> str:
    parts = [f"<b>{title}</b>"]
    for column, label in fields:
        text = _format_geo_value(row.get(column, ""))
        if text:
            parts.append(f"{label}: {text}")
    return "<br>".join(parts)


def _add_geo_point_trace(fig, geo_points, *, name: str, color: str, symbol: str, size: int, fields: list[tuple[str, str]]):
    if geo_points is None or geo_points.empty:
        return
    hover_text = [_point_hover_text(row, fields, name) for _, row in geo_points.iterrows()]
    fig.add_trace(
        go.Scatter(
            x=geo_points.geometry.x,
            y=geo_points.geometry.y,
            mode="markers",
            marker=dict(
                size=size,
                color=color,
                symbol=symbol,
                opacity=0.9,
                line=dict(width=1.2, color="white"),
            ),
            name=f"{name} ({len(geo_points)})",
            hoverinfo="text",
            text=hover_text,
        )
    )


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
):
    """Build the same layered GEO HTML map used in notebook 03, enriched with V3 metrics."""
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "chec_local_matplotlib"))
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
    class_colors = {
        "Bajo": "#2dd4bf",
        "Medio": "#facc15",
        "Alto": "#fb923c",
        "Muy alto": "#dc2626",
    }

    def style_line(feature):
        value = feature["properties"].get(metric_column)
        has_value = bool(feature["properties"].get("has_v3_event"))
        if has_value:
            class_value = feature["properties"].get(metric_class_column) if metric_class_column else None
            if class_value in class_colors:
                return {"color": class_colors[class_value], "weight": 4, "opacity": 0.88}
            rgba = mapper.to_rgba(min(float(value or 0), vmax_robust), bytes=True)
            return {"color": f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}", "weight": 4, "opacity": 0.85}
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
    fmap.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    map_name = fmap.get_name()
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
      window.addEventListener("load", function () {{
        setTimeout(function () {{
          if (window.{map_name}) {{
            window.{map_name}.invalidateSize(true);
          }}
        }}, 150);
      }});
    </script>
    """
    fmap.get_root().html.add_child(folium.Element(render_fix))
    return fmap


from plotly.subplots import make_subplots

def plot_interactive_critical_points(daily_df, critical_points, selected_circuitos=None, start_date=None, end_date=None):
    """
    Plots an interactive timeline of UITI_VANO and event counts, overlaid with critical points.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if not daily_df.empty:
        work = daily_df.copy()
        work["fecha_dia"] = pd.to_datetime(work["fecha_dia"], errors="coerce")

        # Plot event_count (Bar)
        if "event_count" in work.columns:
            fig.add_trace(go.Bar(
                x=work["fecha_dia"],
                y=work["event_count"],
                name="Número de Eventos",
                marker_color='rgba(37, 99, 235, 0.4)',
                hovertemplate="Fecha: %{x|%Y-%m-%d}<br>Eventos: %{y}<extra></extra>"
            ), secondary_y=True)

        # Plot UITI_VANO (Line)
        fig.add_trace(go.Scatter(
            x=work["fecha_dia"],
            y=work["UITI_VANO"],
            mode='lines',
            name="UITI_VANO diario",
            line=dict(color="#19535F", width=2.5),
            hovertemplate="Fecha: %{x|%Y-%m-%d}<br>UITI_VANO: %{y:.2f}<extra></extra>"
        ), secondary_y=False)

        # Plot critical points
        point_dates = [pd.to_datetime(point["fecha_dia"]) for point in critical_points]
        if point_dates:
            point_frame = work[work["fecha_dia"].isin(point_dates)]
            fig.add_trace(go.Scatter(
                x=point_frame["fecha_dia"],
                y=point_frame["UITI_VANO"],
                mode='markers',
                name="Puntos críticos",
                marker=dict(color="#D1495B", size=12, symbol='star', line=dict(color='white', width=1)),
                hovertemplate="<b>Punto Crítico</b><br>Fecha: %{x|%Y-%m-%d}<br>UITI_VANO: %{y:.2f}<extra></extra>"
            ), secondary_y=False)

    circuit_text = ", ".join(selected_circuitos[:4]) if selected_circuitos else "todos los circuitos"
    if selected_circuitos and len(selected_circuitos) > 4:
        circuit_text += f" +{len(selected_circuitos) - 4}"

    total_events = work["event_count"].sum() if "event_count" in work.columns else 0
    total_uiti = work["UITI_VANO"].sum()

    title_text = f"Evolución Diaria (Eventos Totales: {total_events:,.0f} | UITI_VANO Total: {total_uiti:,.2f})<br><sup>Circuito(s): {circuit_text} | {start_date or 'inicio'} a {end_date or 'fin'}</sup>"

    fig.update_layout(
        title=dict(text=title_text, font=dict(size=18, family="Arial, sans-serif")),
        xaxis_title="Fecha",
        plot_bgcolor='#f8fafc',
        paper_bgcolor='#ffffff',
        xaxis=dict(showgrid=True, gridcolor='#e2e8f0', griddash='dot'),
        hovermode="x unified",
        legend=dict(bgcolor='rgba(255, 255, 255, 0.95)', bordercolor='#e2e8f0', borderwidth=1, orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=550,
        margin=dict(l=60, r=60, t=110, b=80),
    )

    # rangemode='tozero' evita que los ejes Y se dibujen por debajo de cero
    fig.update_yaxes(title_text="UITI_VANO", secondary_y=False, showgrid=True, gridcolor='#e2e8f0', griddash='dot', rangemode='tozero')
    fig.update_yaxes(title_text="Número de Eventos", secondary_y=True, showgrid=False, rangemode='tozero')

    return fig


def render_expert_alignment_tab(
    expert_alignment_validation_data,
    *,
    automatic_simulation_table=None,
    automatic_simulation_analysis=None,
    automatic_simulation_cost_context=None,
    automatic_simulation_softmax_curves=None,
    automatic_simulation_risk_maps_html="",
):
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

    def _list_to_items(items, *, max_items: int | None = None) -> str:
        if isinstance(items, dict):
            raw_items = list(items.values())
        elif isinstance(items, list):
            raw_items = items
        else:
            raw_items = [items]
        clean_items = [str(item).strip() for item in raw_items if str(item).strip()]
        if max_items is not None:
            clean_items = clean_items[:max_items]
        if not clean_items:
            return _empty_message()
        lis = "".join(f"<li>{_escape(item)}</li>" for item in clean_items)
        return f"<ul class='report-list'>{lis}</ul>"

    def _risk_category_rank(label) -> int:
        normalized = _clean_text(label).lower()
        if "alto" in normalized and "medio" not in normalized:
            return 3
        if "medio-alto" in normalized or ("medio" in normalized and "alto" in normalized):
            return 2
        if "medio-bajo" in normalized or ("medio" in normalized and "bajo" in normalized):
            return 1
        if "medio" in normalized:
            return 1
        if "bajo" in normalized:
            return 0
        return -1

    def _risk_class_level(label, score=None) -> int | None:
        rank = _risk_category_rank(label)
        if rank >= 0:
            return rank + 1
        parsed = pd.to_numeric(pd.Series([score]), errors="coerce").iloc[0]
        try:
            if pd.isna(parsed):
                return None
        except Exception:
            return None
        return int(max(1, min(4, round(float(parsed)) + 1)))

    def _risk_class_label(level: int | None, label=None) -> str:
        text = _clean_text(label)
        if text:
            return text
        labels = {
            1: "Q1 - Riesgo bajo",
            2: "Q2 - Riesgo medio-bajo",
            3: "Q3 - Riesgo medio-alto",
            4: "Q4 - Riesgo alto",
        }
        return labels.get(level or 0, "Riesgo no disponible")

    def _risk_transition_text(base_label, scenario_label) -> str:
        base = _clean_text(base_label)
        scenario = _clean_text(scenario_label)
        if not base or not scenario:
            return "categoría no disponible"
        if base == scenario:
            return "sin cambio de categoría"
        return f"{base} -> {scenario}"

    def _auto_simulation_chart_html(table) -> str:
        required = {"variable", "riesgo_base", "riesgo_valor_minimo", "riesgo_valor_maximo"}
        if table is None or not hasattr(table, "columns") or not required.issubset(set(table.columns)):
            return (
                "<p class='muted'>No hay columnas suficientes para graficar las clases de riesgo "
                "del simulador automático.</p>"
            )

        work = table.copy()
        for col in ["riesgo_base", "riesgo_valor_minimo", "riesgo_valor_maximo"]:
            work[col] = pd.to_numeric(work[col], errors="coerce")
        work["variable"] = work["variable"].fillna("").astype(str).str.strip()
        work = work[work["variable"] != ""].copy()
        if work.empty:
            return "<p class='muted'>No hay variables válidas para graficar el simulador automático.</p>"

        if "riesgo_base_etiqueta" not in work.columns:
            work["riesgo_base_etiqueta"] = ""
        if "riesgo_valor_minimo_etiqueta" not in work.columns:
            work["riesgo_valor_minimo_etiqueta"] = ""
        if "riesgo_valor_maximo_etiqueta" not in work.columns:
            work["riesgo_valor_maximo_etiqueta"] = ""

        work["nivel_base"] = work.apply(
            lambda row: _risk_class_level(row.get("riesgo_base_etiqueta"), row.get("riesgo_base")),
            axis=1,
        )
        work["nivel_minimo"] = work.apply(
            lambda row: _risk_class_level(row.get("riesgo_valor_minimo_etiqueta"), row.get("riesgo_valor_minimo")),
            axis=1,
        )
        work["nivel_maximo"] = work.apply(
            lambda row: _risk_class_level(row.get("riesgo_valor_maximo_etiqueta"), row.get("riesgo_valor_maximo")),
            axis=1,
        )
        work = work.dropna(subset=["nivel_base", "nivel_minimo", "nivel_maximo"]).copy()
        if work.empty:
            return "<p class='muted'>No hay clases de riesgo válidas para graficar el simulador automático.</p>"
        for col in ["nivel_base", "nivel_minimo", "nivel_maximo"]:
            work[col] = work[col].astype(int).clip(1, 4)
        work["clase_base"] = work.apply(
            lambda row: _risk_class_label(row.get("nivel_base"), row.get("riesgo_base_etiqueta")),
            axis=1,
        )
        work["clase_minimo"] = work.apply(
            lambda row: _risk_class_label(row.get("nivel_minimo"), row.get("riesgo_valor_minimo_etiqueta")),
            axis=1,
        )
        work["clase_maximo"] = work.apply(
            lambda row: _risk_class_label(row.get("nivel_maximo"), row.get("riesgo_valor_maximo_etiqueta")),
            axis=1,
        )
        work["cambia_categoria_minimo"] = work["nivel_minimo"] != work["nivel_base"]
        work["cambia_categoria_maximo"] = work["nivel_maximo"] != work["nivel_base"]
        work["transicion_minimo"] = work.apply(
            lambda row: _risk_transition_text(row.get("clase_base"), row.get("clase_minimo"))
            if row.get("cambia_categoria_minimo")
            else "sin cambio de categoría",
            axis=1,
        )
        work["transicion_maximo"] = work.apply(
            lambda row: _risk_transition_text(row.get("clase_base"), row.get("clase_maximo"))
            if row.get("cambia_categoria_maximo")
            else "sin cambio de categoría",
            axis=1,
        )
        work["cambia_categoria"] = work["cambia_categoria_minimo"] | work["cambia_categoria_maximo"]
        work["salto_categoria_minimo"] = (work["nivel_minimo"] - work["nivel_base"]).abs()
        work["salto_categoria_maximo"] = (work["nivel_maximo"] - work["nivel_base"]).abs()
        work["max_salto_categoria"] = work[["salto_categoria_minimo", "salto_categoria_maximo"]].max(axis=1)
        for col in ["cambio_absoluto_minimo", "cambio_absoluto_maximo", "magnitud_max_cambio_abs"]:
            if col not in work.columns:
                work[col] = 0.0
            work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0.0)
        work["max_cambio_abs"] = work[["cambio_absoluto_minimo", "cambio_absoluto_maximo", "magnitud_max_cambio_abs"]].abs().max(axis=1)
        work = work.sort_values(["max_salto_categoria", "max_cambio_abs"], ascending=[False, False], kind="stable").copy()
        chart_work = work.iloc[::-1].copy()
        transition_rows = work[work["cambia_categoria"]].iloc[::-1].head(5)
        if transition_rows.empty:
            transition_summary = (
                "<p class='muted'>No se observan cambios de categoría de riesgo en las variables graficadas; "
                "la gráfica confirma la estabilidad de clase en los escenarios base, mínimo y máximo.</p>"
            )
        else:
            transition_items = []
            for row in transition_rows.itertuples(index=False):
                changes = []
                if row.cambia_categoria_minimo:
                    changes.append(f"mínimo: {row.transicion_minimo}")
                if row.cambia_categoria_maximo:
                    changes.append(f"máximo: {row.transicion_maximo}")
                transition_items.append(f"<li><strong>{_escape(row.variable)}</strong>: {_escape('; '.join(changes))}</li>")
            transition_summary = (
                "<div class='insight-card'>"
                "<strong>Transiciones de categoría detectadas</strong>"
                f"<ul class='report-list'>{''.join(transition_items)}</ul>"
                "</div>"
            )
        class_legend = (
            "<div class='insight-card'>"
            "<strong>Escala ordinal usada en la gráfica</strong>"
            "<ul class='report-list'>"
            "<li>Q1 - Riesgo bajo</li>"
            "<li>Q2 - Riesgo medio-bajo</li>"
            "<li>Q3 - Riesgo medio-alto</li>"
            "<li>Q4 - Riesgo alto</li>"
            "</ul>"
            "</div>"
        )
        scenario_legend = (
            "<p class='muted'><strong>Escenarios graficados:</strong> Base, valor mínimo y valor máximo "
            "de cada variable priorizada.</p>"
        )

        def _scenario_hover(row, *, scenario: str, risk_value: str, class_value: str, transition: str = "") -> str:
            text = (
                f"Variable: {_clean_text(row.variable)}<br>"
                f"Escenario: {scenario}<br>"
                f"Clase de riesgo: {_clean_text(getattr(row, class_value))}<br>"
                f"Nivel ordinal: {getattr(row, risk_value)} de 4"
            )
            score_col = {
                "Base": "riesgo_base",
                "Mínimo": "riesgo_valor_minimo",
                "Máximo": "riesgo_valor_maximo",
            }.get(scenario)
            if score_col:
                text += f"<br>Score continuo del modelo: {float(getattr(row, score_col)):.4f}"
            if transition:
                text += f"<br>Transición: {_clean_text(getattr(row, transition))}"
            return text

        base_hover = [
            _scenario_hover(row, scenario="Base", risk_value="nivel_base", class_value="clase_base")
            for row in chart_work.itertuples(index=False)
        ]
        min_hover = [
            _scenario_hover(row, scenario="Mínimo", risk_value="nivel_minimo", class_value="clase_minimo", transition="transicion_minimo")
            for row in chart_work.itertuples(index=False)
        ]
        max_hover = [
            _scenario_hover(row, scenario="Máximo", risk_value="nivel_maximo", class_value="clase_maximo", transition="transicion_maximo")
            for row in chart_work.itertuples(index=False)
        ]
        min_colors = ["#d97706" if flag else "#60a5fa" for flag in chart_work["cambia_categoria_minimo"]]
        max_colors = ["#b91c1c" if flag else "#2563eb" for flag in chart_work["cambia_categoria_maximo"]]

        try:
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    y=chart_work["variable"],
                    x=chart_work["nivel_base"],
                    name="Base",
                    orientation="h",
                    marker=dict(color="#64748b"),
                    customdata=base_hover,
                    hovertemplate="%{customdata}<extra></extra>",
                )
            )
            fig.add_trace(
                go.Bar(
                    y=chart_work["variable"],
                    x=chart_work["nivel_minimo"],
                    name="Valor mínimo",
                    orientation="h",
                    marker=dict(color=min_colors),
                    customdata=min_hover,
                    hovertemplate="%{customdata}<extra></extra>",
                )
            )
            fig.add_trace(
                go.Bar(
                    y=chart_work["variable"],
                    x=chart_work["nivel_maximo"],
                    name="Valor máximo",
                    orientation="h",
                    marker=dict(color=max_colors),
                    customdata=max_hover,
                    hovertemplate="%{customdata}<extra></extra>",
                )
            )
            fig.update_layout(
                title=dict(
                    text="Clase de riesgo por variable priorizada: base, mínimo y máximo",
                    font=dict(size=15),
                ),
                xaxis_title="Clase de riesgo",
                yaxis_title="Variable",
                barmode="group",
                height=max(460, 54 * len(chart_work) + 170),
                margin=dict(l=120, r=40, t=70, b=70),
                plot_bgcolor="#f8fafc",
                paper_bgcolor="#ffffff",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                xaxis=dict(
                    range=[0.5, 4.5],
                    tickmode="array",
                    tickvals=[1, 2, 3, 4],
                    ticktext=[
                        "Q1<br>Riesgo bajo",
                        "Q2<br>Riesgo medio-bajo",
                        "Q3<br>Riesgo medio-alto",
                        "Q4<br>Riesgo alto",
                    ],
                    gridcolor="#e2e8f0",
                    dtick=1,
                ),
            )
            chart = fig.to_html(full_html=False, include_plotlyjs=False)
            legend = (
                "<p class='muted'>Cada barra representa la clase ordinal de riesgo del escenario: "
                "Q1 bajo, Q2 medio-bajo, Q3 medio-alto y Q4 alto. Los colores naranja/rojo resaltan "
                "escenarios mínimo o máximo donde la variable cambia de clase frente al riesgo base.</p>"
            )
            return f"<div class='chart-panel'>{transition_summary}{class_legend}{scenario_legend}{chart}{legend}</div>"
        except Exception as exc:
            return f"<p class='muted'>No se pudo generar la gráfica del simulador automático: {_escape(exc)}</p>"

    def _auto_simulation_cost_section() -> str:
        context = automatic_simulation_cost_context if isinstance(automatic_simulation_cost_context, dict) else {}
        if not context:
            return (
                "<h4>Costos aproximados por ítems de contrato</h4>"
                "<p class='muted'>No se entregó contexto de costos para esta ejecución.</p>"
            )
        warnings = context.get("advertencias") if isinstance(context.get("advertencias"), list) else []
        matches = context.get("coincidencias") if isinstance(context.get("coincidencias"), list) else []
        parts = [
            "<h4>Costos aproximados por ítems de contrato</h4>",
            "<p class='muted'>Los costos se estiman por cercanía textual entre variables sensibles del simulador "
            "y apartados del archivo COSTOS ITEMS CONTRATOS.xlsx. Son referencias para discusión económica, "
            "no presupuestos cerrados ni causalidad de intervención.</p>",
        ]
        if warnings:
            parts.append(_list_to_items(warnings, max_items=5))
        if not matches:
            parts.append("<p class='muted'>No hay coincidencias de costos disponibles para mostrar.</p>")
            return "".join(parts)

        rows = []
        for item in matches[:8]:
            if not isinstance(item, dict):
                continue
            variable = item.get("variable", "")
            risk_labels = [
                item.get("riesgo_base_etiqueta", ""),
                item.get("riesgo_valor_minimo_etiqueta", ""),
                item.get("riesgo_valor_maximo_etiqueta", ""),
            ]
            risk_text = " / ".join(str(label).strip() for label in risk_labels if str(label).strip())
            for cost_item in (item.get("items_costo_cercanos") or [])[:3]:
                if not isinstance(cost_item, dict):
                    continue
                cost = cost_item.get("costo_promedio")
                if cost in (None, ""):
                    cost_text = "No disponible"
                else:
                    try:
                        cost_text = f"${float(cost):,.0f}"
                    except (TypeError, ValueError):
                        cost_text = _escape(cost)
                rows.append(
                    "<tr>"
                    f"<td>{_escape(variable)}</td>"
                    f"<td>{_escape(cost_item.get('item_costo', ''))}</td>"
                    f"<td>{_escape(cost_text)}</td>"
                    f"<td>{_escape(cost_item.get('puntaje_cercania', ''))}</td>"
                    f"<td>{_escape(risk_text)}</td>"
                    "</tr>"
                )
        if not rows:
            parts.append("<p class='muted'>No hay ítems de costo cercanos para las variables simuladas.</p>")
            return "".join(parts)
        parts.append(
            "<div class='table-scroll'><table class='compact-table'>"
            "<thead><tr><th>Variable</th><th>Ítem cercano</th><th>Costo promedio</th>"
            "<th>Cercanía</th><th>Etiquetas de riesgo</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
        return "".join(parts)

    def _auto_simulation_softmax_grid_html() -> str:
        context = automatic_simulation_softmax_curves if isinstance(automatic_simulation_softmax_curves, dict) else {}
        variables = context.get("variables") if isinstance(context.get("variables"), list) else []
        variables = [item for item in variables[:4] if isinstance(item, dict) and item.get("filas")]
        if not variables:
            return (
                "<h4>Curvas softmax por clase</h4>"
                "<p class='muted'>No hay datos suficientes para construir la rejilla 2x2 de curvas softmax.</p>"
            )

        class_colors = {
            "Riesgo bajo (Q1)": "#1f77b4",
            "Riesgo medio-bajo (Q2)": "#ff7f0e",
            "Riesgo medio-alto (Q3)": "#2ca02c",
            "Riesgo alto (Q4)": "#d62728",
        }

        def _label_rank(label) -> int:
            text = str(label or "").lower()
            if "q1" in text or ("bajo" in text and "medio" not in text):
                return 0
            if "q2" in text or "medio-bajo" in text or ("medio" in text and "alto" not in text):
                return 1
            if "q3" in text or "medio-alto" in text:
                return 2
            if "q4" in text or "alto" in text:
                return 3
            return 4

        def _dominant_label(row) -> str:
            probs = row.get("probabilidades") if isinstance(row.get("probabilidades"), dict) else {}
            if not probs:
                return ""
            return str(max(probs, key=lambda label: float(probs.get(label, 0.0) or 0.0)))

        def _selected_softmax_row(item) -> tuple[dict, str, float, bool]:
            filas = [row for row in item.get("filas", []) if isinstance(row, dict)]
            candidates = []
            for row in filas:
                dominant = _dominant_label(row)
                rank = _label_rank(dominant)
                probs = row.get("probabilidades") if isinstance(row.get("probabilidades"), dict) else {}
                probability = float(probs.get(dominant, 0.0) or 0.0)
                candidates.append((rank, -probability, float(row.get("riesgo_ordinal_estimado", 99.0) or 99.0), row, dominant, probability))
            valid = [candidate for candidate in candidates if candidate[0] < 3]
            if not valid:
                return {}, "", 0.0, True
            rank, _, _, row, dominant, probability = sorted(valid, key=lambda candidate: candidate[:3])[0]
            return row, dominant, probability, False

        try:
            titles = [_clean_text(item.get("variable")) for item in variables] + [""] * (4 - len(variables))
            fig = make_subplots(rows=2, cols=2, subplot_titles=titles[:4])
            for idx, item in enumerate(variables):
                subplot_row = (idx // 2) + 1
                subplot_col = (idx % 2) + 1
                variable = _clean_text(item.get("variable"))
                filas = [fila for fila in item.get("filas", []) if isinstance(fila, dict)]
                etiquetas = item.get("etiquetas_clase") or []
                for label in etiquetas:
                    clean_label = _clean_text(label)
                    x_values = [fila.get("valor_original") for fila in filas]
                    y_values = [
                        float((fila.get("probabilidades") or {}).get(label, 0.0) or 0.0)
                        for fila in filas
                    ]
                    fig.add_trace(
                        go.Scatter(
                            x=x_values,
                            y=y_values,
                            mode="lines+markers",
                            name=clean_label,
                            legendgroup=clean_label,
                            showlegend=idx == 0,
                            marker=dict(size=6),
                            line=dict(color=class_colors.get(clean_label), width=2),
                            hovertemplate=(
                                f"Variable: {variable}<br>Valor original: %{{x}}<br>"
                                f"Clase: {clean_label}<br>Probabilidad promedio: %{{y:.3f}}<extra></extra>"
                            ),
                        ),
                        row=subplot_row,
                        col=subplot_col,
                    )
                best, best_label, best_probability, kept_quiet = _selected_softmax_row(item)
                if best:
                    fig.add_trace(
                        go.Scatter(
                            x=[best.get("valor_original")],
                            y=[best_probability],
                            mode="markers",
                            name="Valor sugerido",
                            legendgroup="Valor sugerido",
                            showlegend=idx == 0,
                            marker=dict(symbol="star", size=12, color="#111827", line=dict(width=1, color="#ffffff")),
                            hovertemplate=(
                                f"Valor sugerido<br>Clase dominante: {_clean_text(best_label)}<br>"
                                "Valor original: %{x}<br>Probabilidad dominante: %{y:.3f}<extra></extra>"
                            ),
                        ),
                        row=subplot_row,
                        col=subplot_col,
                    )
                fig.update_xaxes(title_text=variable, row=subplot_row, col=subplot_col)
                fig.update_yaxes(title_text="Probabilidad softmax promedio", range=[0, 1], row=subplot_row, col=subplot_col)
            fig.update_layout(
                title=dict(text="Softmax por clase en las 4 variables más relevantes", font=dict(size=15)),
                height=760,
                margin=dict(l=70, r=35, t=95, b=65),
                plot_bgcolor="#f8fafc",
                paper_bgcolor="#ffffff",
                legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1),
            )
            chart = fig.to_html(full_html=False, include_plotlyjs=False)
        except Exception as exc:
            return f"<p class='muted'>No se pudo generar la rejilla de curvas softmax: {_escape(exc)}</p>"

        best_items = []
        quiet_items = []
        for item in variables:
            best, best_label, best_probability, kept_quiet = _selected_softmax_row(item)
            if kept_quiet:
                quiet_items.append(f"<li><strong>{_escape(item.get('variable'))}</strong>: queda quieta porque domina la clase de mayor riesgo.</li>")
                continue
            if not best:
                continue
            risk_value = round(float(best.get("riesgo_ordinal_estimado", 0.0) or 0.0), 3)
            best_items.append(
                "<li>"
                f"<strong>{_escape(item.get('variable'))}</strong>: valor {_escape(best.get('valor_original'))}, "
                f"clase dominante {_escape(best_label)} "
                f"(P={best_probability:.3f}; riesgo ordinal {_escape(risk_value)})"
                "</li>"
            )
        best_summary = (
            "<div class='insight-card'><strong>Valores sugeridos por menor clase dominante</strong>"
            f"<ul class='report-list'>{''.join(best_items)}{''.join(quiet_items)}</ul></div>"
            if best_items or quiet_items
            else ""
        )
        metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
        warnings = [
            str(warning).strip()
            for warning in metadata.get("warnings", [])
            if str(warning).strip()
        ] if isinstance(metadata.get("warnings"), list) else []
        warning_html = _list_to_items(warnings, max_items=5) if warnings else ""
        return (
            "<h4>Curvas softmax por clase</h4>"
            "<p class='muted'>La rejilla muestra, para hasta 4 variables ordenadas por impacto del simulador, "
            "cómo cambia la probabilidad promedio de cada clase de riesgo al recorrer valores originales de la variable. "
            "La estrella marca el primer valor útil donde domina Bajo; si no existe, Medio; luego Alto. "
            "Si solo domina Muy alto, la variable queda quieta.</p>"
            f"{chart}{best_summary}{warning_html}"
        )

    def _auto_simulation_low_risk_cost_estimate() -> str:
        curves = automatic_simulation_softmax_curves if isinstance(automatic_simulation_softmax_curves, dict) else {}
        variables = curves.get("variables") if isinstance(curves.get("variables"), list) else []
        cost_context = automatic_simulation_cost_context if isinstance(automatic_simulation_cost_context, dict) else {}
        matches = cost_context.get("coincidencias") if isinstance(cost_context.get("coincidencias"), list) else []
        match_by_variable = {
            str(item.get("variable", "")).strip(): item
            for item in matches
            if isinstance(item, dict) and str(item.get("variable", "")).strip()
        }
        rows = []
        total_min = 0.0
        total_max = 0.0
        used_costs = 0
        for item in variables[:4]:
            if not isinstance(item, dict):
                continue
            variable = str(item.get("variable", "")).strip()
            best = item.get("mejor_escenario_menor_riesgo") if isinstance(item.get("mejor_escenario_menor_riesgo"), dict) else {}
            match = match_by_variable.get(variable, {})
            cost_items = match.get("items_costo_cercanos") if isinstance(match, dict) and isinstance(match.get("items_costo_cercanos"), list) else []
            numeric_items = []
            for cost_item in cost_items:
                if not isinstance(cost_item, dict):
                    continue
                try:
                    cost = float(cost_item.get("costo_promedio"))
                except (TypeError, ValueError):
                    continue
                numeric_items.append((cost, cost_item))
            if numeric_items:
                numeric_items.sort(key=lambda pair: pair[0])
                chosen_cost, chosen_item = numeric_items[0]
                total_min += chosen_cost
                total_max += max(pair[0] for pair in numeric_items)
                used_costs += 1
                cost_text = f"${chosen_cost:,.0f}"
                item_text = chosen_item.get("item_costo", "")
            else:
                cost_text = "Sin costo cercano"
                item_text = "Sin coincidencia utilizable"
            rows.append(
                "<tr>"
                f"<td>{_escape(variable)}</td>"
                f"<td>{_escape(best.get('valor_original', ''))}</td>"
                f"<td>{_escape(best.get('clase_estimacion', ''))}</td>"
                f"<td>{_escape(item_text)}</td>"
                f"<td>{_escape(cost_text)}</td>"
                "</tr>"
            )
        if not rows:
            return (
                "<h4>Estimación económica orientativa para menor riesgo</h4>"
                "<p class='muted'>No hay curvas softmax suficientes para estimar costos de menor riesgo.</p>"
            )
        if used_costs:
            total_text = f"${total_min:,.0f}"
            if total_max > total_min:
                total_text += f" a ${total_max:,.0f}"
            total_html = (
                "<p class='muted'><strong>Estimación determinística de referencia:</strong> "
                f"{_escape(total_text)} al sumar un ítem cercano por variable con costo disponible. "
                "Esta suma no es un presupuesto: solo coteja el menor riesgo estimado por el modelo con los "
                "apartados de contrato más cercanos encontrados en el Excel.</p>"
            )
        else:
            total_html = "<p class='muted'>No hay costos numéricos cercanos suficientes para calcular una suma orientativa.</p>"
        return (
            "<h4>Estimación económica orientativa para menor riesgo</h4>"
            "<p class='muted'>Para cada variable de la rejilla se toma el valor probado con menor riesgo ordinal "
            "estimado y se coteja con el ítem de contrato cercano de menor costo promedio disponible.</p>"
            "<div class='table-scroll'><table class='compact-table'>"
            "<thead><tr><th>Variable</th><th>Valor de menor riesgo</th><th>Clase estimada</th>"
            "<th>Ítem de costo usado</th><th>Costo de referencia</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            f"{total_html}"
        )

    def _auto_simulation_brief_comparison() -> str:
        curves = automatic_simulation_softmax_curves if isinstance(automatic_simulation_softmax_curves, dict) else {}
        variables = [item for item in (curves.get("variables") or [])[:4] if isinstance(item, dict) and item.get("filas")]
        if not variables:
            return (
                "<div class='summary-box'>"
                "<h3 style='margin-top:0;'>Comparación breve del simulador</h3>"
                "<p class='muted'>No hay curvas softmax suficientes para comparar los valores sugeridos.</p>"
                "</div>"
            )
        def _label_rank(label) -> int:
            text = str(label or "").lower()
            if "bajo" in text and "medio" not in text:
                return 0
            if "medio-bajo" in text or ("medio" in text and "alto" not in text):
                return 1
            if "medio-alto" in text:
                return 2
            if "alto" in text:
                return 3
            return 4

        def _dominant_label(row) -> str:
            probs = row.get("probabilidades") if isinstance(row.get("probabilidades"), dict) else {}
            if not probs:
                return ""
            return str(max(probs, key=lambda label: float(probs.get(label, 0.0) or 0.0)))

        selected = []
        kept = []
        for item in variables:
            filas = [row for row in item.get("filas", []) if isinstance(row, dict)]
            if not filas:
                continue
            candidates = []
            for row in filas:
                dominant = _dominant_label(row)
                rank = _label_rank(dominant)
                candidates.append((rank, row, dominant))
            valid_candidates = [item for item in candidates if item[0] < 3]
            if not valid_candidates:
                kept.append(str(item.get("variable", "")).strip())
                continue
            best_rank, best_row, dominant = sorted(
                valid_candidates,
                key=lambda item: (
                    item[0],
                    float(best_row_probs.get(item[2], 0.0) if (best_row_probs := (item[1].get("probabilidades") or {})) else 0.0) * -1,
                    float(item[1].get("riesgo_ordinal_estimado", 99.0) or 99.0),
                ),
            )[0]
            selected.append(
                f"{_clean_text(item.get('variable'))}: valor {_clean_text(best_row.get('valor_original'))} "
                f"con clase dominante {_clean_text(dominant)}"
            )
        if not selected:
            return ""
        kept_html = (
            f"<li>Sin configuración de reducción útil: {_escape(', '.join(kept))}. "
            "Esas columnas se dejan quietas porque la clase de mayor probabilidad sigue siendo la de mayor riesgo.</li>"
            if kept
            else ""
        )
        return (
            "<div class='summary-box'>"
            "<h3 style='margin-top:0;'>Comparación breve del simulador</h3>"
            "<ul class='report-list'>"
            "<li>Para cada variable se busca primero una configuración donde domine riesgo bajo; si no existe, riesgo medio; si tampoco existe, riesgo alto.</li>"
            f"<li>{_escape('; '.join(selected))}</li>"
            f"{kept_html}"
            "</ul>"
            "</div>"
        )

    def _post_prioritization_simulator_visuals() -> str:
        table = automatic_simulation_table
        has_table = table is not None and hasattr(table, "empty") and not table.empty
        has_curves = isinstance(automatic_simulation_softmax_curves, dict) and bool(
            automatic_simulation_softmax_curves.get("variables")
        )
        if not has_table and not has_curves and not automatic_simulation_risk_maps_html:
            return ""
        parts = [
            "<div class='content-box'>",
            "<h3 style='margin-top:0;'>Gráficas del simulador automático</h3>",
        ]
        if has_curves:
            parts.append(_auto_simulation_softmax_grid_html())
        parts.append(_auto_simulation_brief_comparison())
        if automatic_simulation_risk_maps_html:
            parts.append(automatic_simulation_risk_maps_html)
        parts.append("</div>")
        return "".join(parts)

    def _section_items(key, title, fields):
        items = analysis.get(key, []) if analysis else []
        body = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    if str(item).strip():
                        body.append(f"<li>{_escape(item)}</li>")
                    continue
                lead = item.get("tema") or item.get("variable") or item.get("fuente") or "Hallazgo"
                details = []
                for field, label in fields:
                    value = item.get(field)
                    if value in (None, "", []):
                        continue
                    details.append(f"<span><strong>{_escape(label)}:</strong> {_value(value)}</span>")
                body.append(
                    "<li>"
                    f"<strong>{_escape(lead)}</strong>"
                    f"<div class='item-details'>{''.join(details)}</div>"
                    "</li>"
                )
        content = f"<ul class='report-list'>{''.join(body)}</ul>" if body else _empty_message()
        return (
            "<div class='content-box'>"
            f"<h3 style='margin-top:0;'>{_escape(title)}</h3>"
            f"{content}"
            "</div>"
        )

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

    def _auto_simulation_section():
        table = automatic_simulation_table
        analysis_data = automatic_simulation_analysis or {}
        has_table = table is not None and hasattr(table, "empty") and not table.empty
        has_analysis = isinstance(analysis_data, dict) and bool(analysis_data)
        if not has_table and not has_analysis:
            return ""

        parts = [
            "<div class='content-box'>",
            "<h3 style='margin-top:0;'>Análisis automático de sensibilidad por escenarios mínimo/máximo</h3>",
        ]
        if has_table:
            display_columns = [
                ("variable", "Variable"),
                ("valor_original_base", "Valor base"),
                ("valor_minimo_usado", "Mínimo usado"),
                ("valor_maximo_usado", "Máximo usado"),
                ("riesgo_base", "Riesgo base"),
                ("riesgo_valor_minimo", "Riesgo mínimo"),
                ("riesgo_valor_maximo", "Riesgo máximo"),
                ("cambio_absoluto_minimo", "Cambio mín."),
                ("cambio_absoluto_maximo", "Cambio máx."),
                ("direccion_cambio_minimo", "Dirección mín."),
                ("direccion_cambio_maximo", "Dirección máx."),
                ("observacion", "Observación"),
            ]
            available_columns = [(col, label) for col, label in display_columns if col in table.columns]

            def _format_cell(value):
                try:
                    if pd.isna(value):
                        return ""
                except Exception:
                    pass
                if isinstance(value, float):
                    return f"{value:.4f}"
                return _escape(value)

            rows = []
            for _, row in table.head(20).iterrows():
                rows.append(
                    "<tr>"
                    + "".join(f"<td>{_format_cell(row.get(col))}</td>" for col, _ in available_columns)
                    + "</tr>"
                )
            head = "".join(f"<th>{_escape(label)}</th>" for _, label in available_columns)
            parts.append(
                "<div class='table-scroll'><table class='compact-table'>"
                f"<thead><tr>{head}</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div>"
            )
            if len(table) > 20:
                parts.append(f"<p class='muted'>Se muestran 20 de {len(table)} variables simuladas.</p>")
            parts.append(_auto_simulation_cost_section())
            parts.append(_auto_simulation_low_risk_cost_estimate())
        else:
            parts.append("<p class='muted'>La tabla del simulador automático no está disponible para esta ejecución.</p>")
            parts.append(_auto_simulation_cost_section())
            parts.append(_auto_simulation_low_risk_cost_estimate())

        if has_analysis:
            for key, title in [
                ("resumen", "Resumen del agente"),
                ("variables_mas_sensibles", "Variables más sensibles"),
                ("patrones_minimo_maximo", "Patrones mínimo/máximo"),
                ("hallazgos_para_criticidad", "Hallazgos útiles para criticidad"),
                ("limitaciones", "Limitaciones"),
                ("contexto_reutilizado", "Contexto reutilizado"),
            ]:
                items = analysis_data.get(key)
                if not items:
                    continue
                if key == "variables_mas_sensibles" and isinstance(items, list):
                    rendered = []
                    for item in items[:5]:
                        if isinstance(item, dict):
                            variable = item.get("variable", "")
                            lectura = item.get("lectura", "")
                            cambio = item.get("mayor_cambio_abs", "")
                            rendered.append(
                                f"{_escape(variable)}: {_escape(lectura)}"
                                + (f" (mayor cambio abs.: {_escape(cambio)})" if cambio not in (None, "") else "")
                            )
                        elif str(item).strip():
                            rendered.append(str(item).strip())
                    parts.append(f"<h4>{_escape(title)}</h4>{_list_to_items(rendered, max_items=5)}")
                else:
                    parts.append(f"<h4>{_escape(title)}</h4>{_list_to_items(items, max_items=5)}")
        parts.append("</div>")
        return "".join(parts)

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
            f"<li><strong>Periodo:</strong> {_escape(periodo.get('inicio'))} a {_escape(periodo.get('fin'))}</li>"
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
        + _post_prioritization_simulator_visuals()
        + synthesis_html
    )


def render_llm_analysis(
    validation_data: dict,
    raw_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    critical_points: list[dict],
    selected_circuitos: list[str],
    start_date: str = None,
    end_date: str = None,
    output_dir: str | Path = PROJECT_ROOT / "reports" / "interpretability" / "html",
    llm_model: str = "Desconocido",
    llm_provider: str = "Desconocido",
    inference_results: dict | None = None,
    inference_analysis: dict | None = None,
    expert_alignment_analysis: dict | None = None,
    expert_alignment_matches: list[dict] | None = None,
    automatic_simulation_table=None,
    automatic_simulation_analysis: dict | None = None,
    automatic_simulation_cost_context: dict | None = None,
    automatic_simulation_softmax_curves: dict | None = None,
    automatic_simulation_vano_risk_df=None,
):
    """
    Renders the structured JSON output from the LLM into a beautiful HTML format
    suitable for Jupyter Notebooks, incorporating interactive Plotly charts.
    """
    from IPython.display import display, Markdown, HTML
    from datetime import datetime
    import os

    validation_data = validation_data or {}

    # Generate Plotly figures
    fig_events = plot_interactive_circuit_events(raw_df, start_date, end_date)
    fig_sums = plot_interactive_uiti_vano_sums(raw_df, start_date, end_date)
    fig_clusters = plot_interactive_circuit_clustering(raw_df, start_date, end_date, highlighted_circuits=selected_circuitos)
    fig_critical = plot_interactive_critical_points(daily_df, critical_points, selected_circuitos, start_date, end_date)

    primary_circuit = selected_circuitos[0] if selected_circuitos else "TODOS"

    html_map_events = ""
    html_map_uiti = ""
    if primary_circuit != "TODOS":
        try:
            map_events = plot_circuit_map_folium(
                raw_df,
                primary_circuit,
                date_range=(start_date, end_date) if start_date or end_date else None,
                color_target="number_of_events",
            )
            html_map_events = map_events.get_root().render()
        except Exception as exc:
            html_map_events = f"<p class='muted'>No se pudo renderizar el mapa GEO por eventos: {exc}</p>"
        try:
            map_uiti = plot_circuit_map_folium(
                raw_df,
                primary_circuit,
                date_range=(start_date, end_date) if start_date or end_date else None,
                color_target="UITI_VANO_sum",
            )
            html_map_uiti = map_uiti.get_root().render()
        except Exception as exc:
            html_map_uiti = f"<p class='muted'>No se pudo renderizar el mapa GEO por UITI_VANO: {exc}</p>"

    # Convert figures to HTML snippets
    html_events = fig_events.to_html(full_html=False, include_plotlyjs='cdn') if fig_events else ""
    html_sums = fig_sums.to_html(full_html=False, include_plotlyjs='cdn') if fig_sums else ""
    html_clusters = fig_clusters.to_html(full_html=False, include_plotlyjs='cdn') if fig_clusters else ""
    html_critical = fig_critical.to_html(full_html=False, include_plotlyjs='cdn') if fig_critical else ""

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

    def _simulator_risk_maps_html() -> str:
        table = automatic_simulation_table
        curves = automatic_simulation_softmax_curves if isinstance(automatic_simulation_softmax_curves, dict) else {}
        vano_risk = automatic_simulation_vano_risk_df
        curve_variables = [item for item in (curves.get("variables") or [])[:4] if isinstance(item, dict) and item.get("filas")]
        if primary_circuit == "TODOS":
            return ""
        if not {"CIRCUITO", "FID_VANO", "UITI_VANO"}.issubset(set(raw_df.columns)):
            return ""

        def _risk_class_name(value) -> str:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = 1.0
            level = int(max(1, min(4, round(numeric))))
            return {1: "Bajo", 2: "Medio", 3: "Alto", 4: "Muy alto"}[level]

        def _label_rank(label) -> int:
            text = str(label or "").lower()
            if "bajo" in text and "medio" not in text:
                return 0
            if "medio-bajo" in text or ("medio" in text and "alto" not in text):
                return 1
            if "medio-alto" in text:
                return 2
            if "alto" in text:
                return 3
            return 4

        def _dominant_label(row) -> str:
            probs = row.get("probabilidades") if isinstance(row.get("probabilidades"), dict) else {}
            if not probs:
                return ""
            return str(max(probs, key=lambda label: float(probs.get(label, 0.0) or 0.0)))

        def _best_risk_reduction_rows() -> tuple[list[dict[str, object]], list[str]]:
            selected = []
            kept = []
            for item in curve_variables:
                filas = [row for row in item.get("filas", []) if isinstance(row, dict)]
                if not filas:
                    continue
                candidates = []
                for row in filas:
                    dominant = _dominant_label(row)
                    rank = _label_rank(dominant)
                    probs = row.get("probabilidades") if isinstance(row.get("probabilidades"), dict) else {}
                    dominant_probability = float(probs.get(dominant, 0.0) or 0.0)
                    candidates.append((rank, -dominant_probability, float(row.get("riesgo_ordinal_estimado", 99.0) or 99.0), row, dominant))
                valid_candidates = [candidate for candidate in candidates if candidate[0] < 3]
                if not valid_candidates:
                    kept.append(str(item.get("variable", "")).strip())
                    continue
                rank, neg_probability, risk_value, best_row, dominant = sorted(valid_candidates, key=lambda candidate: candidate[:3])[0]
                selected.append(
                    {
                        "variable": item.get("variable", ""),
                        "valor": best_row.get("valor_original"),
                        "prob_dominante": abs(float(neg_probability)),
                        "riesgo_ordinal": risk_value,
                        "clase": best_row.get("clase_estimacion", ""),
                        "dominante": dominant,
                    }
                )
            return selected, kept

        work = raw_df[raw_df["CIRCUITO"].astype(str).eq(str(primary_circuit))].copy()
        if start_date is not None or end_date is not None:
            work["FECHA_parsed"] = pd.to_datetime(work["FECHA"], errors="coerce") if "FECHA" in work.columns else pd.NaT
            if start_date is not None:
                work = work[work["FECHA_parsed"] >= pd.to_datetime(start_date)]
            if end_date is not None:
                work = work[work["FECHA_parsed"] <= pd.to_datetime(end_date)]
        if work.empty:
            return ""

        work["FID_VANO_NORM"] = _norm_map_id(work["FID_VANO"])
        work["UITI_VANO_NUM"] = pd.to_numeric(work["UITI_VANO"], errors="coerce").fillna(0.0)
        uiti_by_vano = work.groupby("FID_VANO_NORM")["UITI_VANO_NUM"].sum()
        uiti_by_vano = uiti_by_vano[uiti_by_vano.index.notna()]
        if uiti_by_vano.empty:
            return ""

        if uiti_by_vano.nunique() >= 4:
            risk_levels = pd.qcut(uiti_by_vano.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(float)
        else:
            max_value = float(uiti_by_vano.max()) or 1.0
            risk_levels = (1.0 + 3.0 * (uiti_by_vano / max_value)).clip(1.0, 4.0)
        original_classes = risk_levels.apply(_risk_class_name)

        if vano_risk is not None and hasattr(vano_risk, "empty") and not vano_risk.empty:
            required_vano_cols = {"FID_VANO", "simulado_riesgo_ordinal", "simulado_clase"}
            if required_vano_cols.issubset(set(vano_risk.columns)):
                risk_work = vano_risk.copy()
                risk_work["FID_VANO_NORM"] = _norm_map_id(risk_work["FID_VANO"])
                suggested_levels = (
                    pd.to_numeric(risk_work.set_index("FID_VANO_NORM")["simulado_riesgo_ordinal"], errors="coerce")
                    + 1.0
                ).clip(1.0, 4.0)

                def _simple_model_class(label) -> str:
                    text = str(label or "").lower()
                    if "q1" in text or ("bajo" in text and "medio" not in text):
                        return "Bajo"
                    if "q2" in text or "medio-bajo" in text or ("medio" in text and "alto" not in text):
                        return "Medio"
                    if "q3" in text or "medio-alto" in text:
                        return "Alto"
                    return "Muy alto"

                suggested_classes = risk_work.set_index("FID_VANO_NORM")["simulado_clase"].map(_simple_model_class)
                applied_text = ""
                if "variables_aplicadas" in risk_work.columns:
                    applied_text = str(risk_work["variables_aplicadas"].dropna().iloc[0]) if not risk_work["variables_aplicadas"].dropna().empty else ""
                quiet_text = ""
                if "variables_quietas" in risk_work.columns:
                    quiet_text = str(risk_work["variables_quietas"].dropna().iloc[0]) if not risk_work["variables_quietas"].dropna().empty else ""
                try:
                    original_map = plot_circuit_map_folium(
                        raw_df,
                        primary_circuit,
                        date_range=(start_date, end_date) if start_date or end_date else None,
                        metric_by_vano=risk_levels,
                        metric_label="Nivel de riesgo original por UITI_VANO",
                        metric_column="riesgo_original_uiti",
                        metric_class_by_vano=original_classes,
                        metric_class_column="clase",
                    )
                    suggested_map = plot_circuit_map_folium(
                        raw_df,
                        primary_circuit,
                        date_range=(start_date, end_date) if start_date or end_date else None,
                        metric_by_vano=suggested_levels,
                        metric_label="Clase predicha promedio por vano",
                        metric_column="riesgo_predicho_simulador",
                        metric_class_by_vano=suggested_classes,
                        metric_class_column="clase",
                    )
                except Exception as exc:
                    return f"<p class='muted'>No se pudo renderizar el comparativo GEO del simulador: {_escape(exc)}</p>"
                quiet_html = f"<li>Variables quietas: {_escape(quiet_text)}.</li>" if quiet_text else ""
                discussion = (
                    "<div class='summary-box'>"
                    "<h3 style='margin-top:0;'>Discusión breve del mapa comparativo</h3>"
                    "<ul class='report-list'>"
                    "<li>El mapa izquierdo clasifica cada vano por UITI_VANO acumulado observado en el periodo.</li>"
                    "<li>El mapa derecho usa predicción del modelo: para cada registro simulado se calculan probabilidades "
                    "softmax y luego se promedian por FID_VANO; la clase del vano es la clase con mayor probabilidad promedio.</li>"
                    "<li>Se usa promedio, no suma, para que un vano con más registros no cambie de clase solo por aparecer más veces.</li>"
                    f"<li>Variables aplicadas en la simulación: {_escape(applied_text or 'ninguna')}.</li>"
                    f"{quiet_html}"
                    "</ul>"
                    "</div>"
                )
                panels = (
                    _chart_panel("Mapa de riesgo original - UITI_VANO", _iframe_srcdoc(original_map.get_root().render(), height=560))
                    + _chart_panel("Mapa de clase predicha - simulador", _iframe_srcdoc(suggested_map.get_root().render(), height=560))
                )
                return (
                    "<h4>Mapa comparativo de riesgo por vano</h4>"
                    f"<div class='chart-grid two-col'>{panels}</div>"
                    f"{discussion}"
                )

        if table is None or not hasattr(table, "empty") or table.empty or not curve_variables:
            return ""
        required = {"riesgo_base"}
        if not required.issubset(set(table.columns)):
            return ""

        sim = table.copy()
        sim["riesgo_base"] = pd.to_numeric(sim["riesgo_base"], errors="coerce")
        baseline_risk = float(sim["riesgo_base"].dropna().mean()) if not sim["riesgo_base"].dropna().empty else 1.0
        selected_rows, kept_variables = _best_risk_reduction_rows()
        if not selected_rows:
            return ""

        suggested_score = risk_levels.astype(float).copy()
        applied_variables = 0
        for item in selected_rows:
            variable = str(item.get("variable", "")).strip()
            if not variable or variable not in work.columns:
                kept_variables.append(variable)
                continue
            current_values = pd.to_numeric(work[variable], errors="coerce")
            if current_values.dropna().empty:
                kept_variables.append(variable)
                continue
            current_by_vano = current_values.groupby(work["FID_VANO_NORM"]).median()
            try:
                target_value = float(item.get("valor"))
            except (TypeError, ValueError):
                kept_variables.append(variable)
                continue
            spread = float(current_values.quantile(0.95) - current_values.quantile(0.05))
            if not np.isfinite(spread) or spread <= 0:
                spread = float(current_values.max() - current_values.min())
            if not np.isfinite(spread) or spread <= 0:
                kept_variables.append(variable)
                continue
            distance = (current_by_vano - target_value).abs() / spread
            distance = distance.reindex(suggested_score.index).fillna(0.0).clip(0.0, 1.0)
            improvement = max(0.0, baseline_risk - float(item.get("riesgo_ordinal", baseline_risk)))
            if improvement <= 0:
                kept_variables.append(variable)
                continue
            suggested_score = suggested_score - (distance * improvement / max(1, len(selected_rows)))
            applied_variables += 1
        if applied_variables == 0:
            suggested_score = risk_levels.astype(float).copy()

        if suggested_score.nunique() >= 4:
            suggested_levels = pd.qcut(suggested_score.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(float)
        else:
            suggested_levels = suggested_score.clip(1.0, 4.0)
        suggested_classes = suggested_levels.apply(_risk_class_name)

        try:
            original_map = plot_circuit_map_folium(
                raw_df,
                primary_circuit,
                date_range=(start_date, end_date) if start_date or end_date else None,
                metric_by_vano=risk_levels,
                metric_label="Nivel de riesgo original por UITI_VANO",
                metric_column="riesgo_original_uiti",
                metric_class_by_vano=original_classes,
                metric_class_column="clase",
            )
            suggested_map = plot_circuit_map_folium(
                raw_df,
                primary_circuit,
                date_range=(start_date, end_date) if start_date or end_date else None,
                metric_by_vano=suggested_levels,
                metric_label="Nivel de riesgo sugerido por simulador",
                metric_column="riesgo_sugerido_simulador",
                metric_class_by_vano=suggested_classes,
                metric_class_column="clase",
            )
        except Exception as exc:
            return f"<p class='muted'>No se pudo renderizar el comparativo GEO del simulador: {_escape(exc)}</p>"

        selected_items = "".join(
            "<li>"
            f"<strong>{_escape(row['variable'])}</strong>: valor {_escape(row['valor'])}, "
            f"clase dominante {_escape(row['dominante'])} "
            f"(P={float(row['prob_dominante']):.3f})"
            "</li>"
            for row in selected_rows
        )
        kept_items = "".join(f"<li>{_escape(variable)} queda quieta.</li>" for variable in sorted(set(kept_variables)) if variable)
        unchanged_note = (
            "<h4>Variables sin cambio</h4>"
            f"<ul class='report-list'>{kept_items}</ul>"
            if kept_items
            else ""
        )
        discussion = (
            "<div class='summary-box'>"
            "<h3 style='margin-top:0;'>Discusión breve del mapa comparativo</h3>"
            "<ul class='report-list'>"
            "<li>El mapa izquierdo clasifica cada vano con eventos por cuartiles del UITI_VANO agregado "
            "en el periodo analizado, usando solo las clases Bajo, Medio, Alto y Muy alto.</li>"
            "<li>El mapa derecho agrupa por el mismo FID_VANO y ajusta el score espacial según qué tan lejos está "
            "cada vano de los valores sugeridos por el simulador para las variables modificables.</li>"
            "<li>Si ambos mapas se parecen, significa que los valores sugeridos no alteran el orden espacial de los "
            "vanos o que varias variables quedaron quietas porque no hubo una configuración con menor clase dominante.</li>"
            "</ul>"
            "<h4>Valores sugeridos por softmax</h4>"
            f"<ul class='report-list'>{selected_items}</ul>"
            f"{unchanged_note}"
            "</div>"
        )
        panels = (
            _chart_panel("Mapa de riesgo original - UITI_VANO", _iframe_srcdoc(original_map.get_root().render(), height=560))
            + _chart_panel("Mapa de riesgo sugerido - simulador", _iframe_srcdoc(suggested_map.get_root().render(), height=560))
        )
        return (
            "<h4>Mapa comparativo de riesgo por vano</h4>"
            f"<div class='chart-grid two-col'>{panels}</div>"
            f"{discussion}"
        )

    def _graph_panel(title, graph_path):
        if not graph_path:
            return ""
        path = Path(graph_path)
        try:
            href = path.resolve().as_uri()
        except Exception:
            href = str(path)
        return (
            f"<div class='chart-panel graph-panel'>"
            f"<h3>{_escape(title)}</h3>"
            f"<div class='graph-actions'><a href='{_escape(href)}' target='_blank'>Abrir grafo interactivo</a></div>"
            f"<iframe src='{_escape(href)}' loading='lazy'></iframe>"
            f"</div>"
        )

    def _render_inference_layout(results, analysis):
        if not results:
            return "", ""
        analysis = analysis or {}
        analysis_by_name = {}
        for scenario in analysis.get("escenarios", []) if isinstance(analysis, dict) else []:
            if isinstance(scenario, dict) and scenario.get("nombre"):
                analysis_by_name[str(scenario["nombre"])] = scenario

        hallazgos = analysis.get("hallazgos", []) if isinstance(analysis, dict) else []
        graph_discussions = analysis.get("discusion_grafos", []) if isinstance(analysis, dict) else []
        graph_discussions_by_section = {"periodo_completo": [], "puntos_criticos": []}
        graph_discussions_general = []

        def _normalizar_seccion_grafo(value):
            text = str(value or "").strip().lower()
            if any(token in text for token in ["critico", "crítico", "punto", "fecha"]):
                return "puntos_criticos"
            if any(token in text for token in ["periodo", "período", "completo", "general"]):
                return "periodo_completo"
            return ""

        for item in graph_discussions if isinstance(graph_discussions, list) else []:
            if isinstance(item, dict):
                section = _normalizar_seccion_grafo(
                    item.get("seccion") or item.get("section") or item.get("apartado") or item.get("escenario") or item.get("nombre")
                )
                text = str(
                    item.get("lectura")
                    or item.get("interpretacion")
                    or item.get("discusion")
                    or item.get("texto")
                    or ""
                ).strip()
                if section and text:
                    graph_discussions_by_section.setdefault(section, []).append(text)
                elif text:
                    graph_discussions_general.append(text)
            elif str(item).strip():
                graph_discussions_general.append(str(item).strip())
        if not graph_discussions_general and not any(graph_discussions_by_section.values()):
            coherencia_items = analysis.get("coherencia_grafo_modelo", []) if isinstance(analysis, dict) else []
            for item in coherencia_items if isinstance(coherencia_items, list) else []:
                if isinstance(item, dict):
                    text = str(item.get("lectura") or item.get("ruta_resumida") or item).strip()
                else:
                    text = str(item).strip()
                if text:
                    graph_discussions_general.append(text)

        def _graph_discussion_items(section):
            items = list(graph_discussions_by_section.get(section, []))
            if not items:
                items = list(graph_discussions_general)
            return items

        def _as_items(value):
            if isinstance(value, list):
                return [str(item).strip() for item in value if str(item).strip()]
            if isinstance(value, dict):
                return [
                    str(item).strip()
                    for item in value.values()
                    if str(item).strip()
                ]
            text = str(value or "").strip()
            return [text] if text else []

        def _hypothesis_items(section, scenario_texts, graph_items):
            hypotheses = analysis.get("hipotesis_modelo_predictivo", {}) if isinstance(analysis, dict) else {}
            explicit = []
            if isinstance(hypotheses, dict):
                candidates = [hypotheses.get(section), hypotheses.get(section.replace("_", " "))]
                if section == "periodo_completo":
                    candidates.extend([hypotheses.get("periodo"), hypotheses.get("general")])
                elif section == "puntos_criticos":
                    candidates.extend([hypotheses.get("puntos críticos"), hypotheses.get("puntos criticos")])
                for candidate in candidates:
                    explicit = _as_items(candidate)
                    if explicit:
                        break
            elif isinstance(hypotheses, list):
                for item in hypotheses:
                    if not isinstance(item, dict):
                        continue
                    item_section = _normalizar_seccion_grafo(item.get("seccion") or item.get("section") or item.get("apartado"))
                    if item_section == section:
                        explicit.extend(_as_items(item.get("items") or item.get("hipotesis") or item.get("texto")))
            if explicit:
                return explicit
            sources = [text for text in scenario_texts if str(text).strip()]
            sources.extend(str(item).strip() for item in graph_items if str(item).strip())
            if not sources:
                return []
            if section == "periodo_completo":
                lead = "La hipótesis del modelo predictivo para el período completo integra las señales de recurrencia, severidad y grafos estimados."
            else:
                lead = "La hipótesis del modelo predictivo para los puntos críticos integra las señales focalizadas por fecha y los grafos estimados."
            return [lead, *sources[:4]]

        def _scenario_interpretation(result):
            if not isinstance(result, dict):
                return ""
            contexto = result.get("contexto", {})
            nombre = str(contexto.get("nombre") or "")
            escenario_llm = analysis_by_name.get(nombre, {})
            return str(escenario_llm.get("interpretacion") or result.get("interpretacion") or "").strip()

        def _scenario_discussion_panel(title, result):
            text = _scenario_interpretation(result)
            if not text:
                return ""
            return f"<div class='content-box'><h3 style='margin-top:0;'>{_escape(title)}</h3>{_text_to_items(text)}</div>"

        def _result_block(key, result, heading):
            if not isinstance(result, dict):
                return ""
            interpretacion = _scenario_interpretation(result)
            html_barras = _figure_html(result.get("fig_barras"), f"Barras - {heading}")
            html_radar = _figure_html(result.get("fig_radar"), f"Radar - {heading}")

            html_parts = [f"<h3>{_escape(heading)}</h3>"]
            if interpretacion:
                html_parts.append(f"<div class='content-box'>{_text_to_items(interpretacion)}</div>")
            chart_panels = [
                _chart_panel(f"Barras - {heading}", html_barras),
                _chart_panel(f"Radar - {heading}", html_radar),
            ]
            html_parts.append(f"<div class='chart-grid two-col'>{''.join(panel for panel in chart_panels if panel)}</div>")
            return "\n".join(html_parts)

        top_uiti = results.get("top_uiti_periodo")
        top_frecuencia = results.get("top_frecuencia_periodo")
        puntos_criticos_uiti = results.get("top_uiti_puntos_criticos")
        puntos_criticos_frecuencia = results.get("top_frecuencia_puntos_criticos")

        barras_periodo = []
        radares_periodo = []
        if top_frecuencia:
            barras_periodo.append(_chart_panel(
                "Número de eventos",
                _figure_html(top_frecuencia.get("fig_barras")),
            ))
            radares_periodo.append(_chart_panel(
                "Radar - Número de eventos",
                _figure_html(top_frecuencia.get("fig_radar")),
            ))
        if top_uiti:
            barras_periodo.append(_chart_panel(
                "Gravedad",
                _figure_html(top_uiti.get("fig_barras")),
            ))
            radares_periodo.append(_chart_panel(
                "Radar - Gravedad",
                _figure_html(top_uiti.get("fig_radar")),
            ))
        grafos_periodo = []
        if top_frecuencia:
            grafos_periodo.append(_graph_panel(
                "Grafo estimado - Número de eventos",
                top_frecuencia.get("grafo_interactivo"),
            ))
        if top_uiti:
            grafos_periodo.append(_graph_panel(
                "Grafo estimado - Gravedad",
                top_uiti.get("grafo_interactivo"),
            ))

        characterization_parts = []
        max_conclusion_items = 5
        hallazgo_texts = [str(item).strip() for item in hallazgos if str(item).strip()]
        general_sections = []
        period_scenario_texts = []
        if hallazgo_texts:
            general_sections.append(
                "<h4>Síntesis general</h4>"
                + _list_to_items(hallazgo_texts, max_items=max_conclusion_items)
            )
            period_scenario_texts.extend(hallazgo_texts)
        if top_frecuencia:
            text_freq = _scenario_interpretation(top_frecuencia)
            if text_freq:
                period_scenario_texts.append(text_freq)
                general_sections.append(
                    "<h4>Número de Eventos</h4>"
                    + _text_to_items(text_freq, max_items=max_conclusion_items)
                )
        if top_uiti:
            text_uiti = _scenario_interpretation(top_uiti)
            if text_uiti:
                period_scenario_texts.append(text_uiti)
                general_sections.append(
                    "<h4>UITI_VANO</h4>"
                    + _text_to_items(text_uiti, max_items=max_conclusion_items)
                )
        graph_discussion_periodo = _graph_discussion_items("periodo_completo")
        hypothesis_periodo = _hypothesis_items("periodo_completo", period_scenario_texts, graph_discussion_periodo)
        if general_sections:
            characterization_parts.append(
                "<div class='summary-box'><h3 style='margin-top:0;'>Discusión general de inferencias del modelo</h3>"
                + "".join(general_sections)
                + "</div>"
            )
        if hypothesis_periodo:
            characterization_parts.append(
                "<div class='summary-box' style='background: #fffbeb; border-left: 5px solid #fbbf24;'>"
                "<h3 style='margin-top:0; color:#b45309;'>Hipótesis del modelo predictivo — período completo</h3>"
                + _list_to_items(hypothesis_periodo, max_items=max_conclusion_items)
                + "</div>"
            )
        if barras_periodo:
            characterization_parts.append("<h3>Barras por escenario</h3>")
            characterization_parts.append(f"<div class='chart-grid two-col'>{''.join(barras_periodo)}</div>")
        if radares_periodo:
            characterization_parts.append("<h3>Radares por escenario</h3>")
            characterization_parts.append(f"<div class='chart-grid'>{''.join(radares_periodo)}</div>")
        if grafos_periodo:
            if graph_discussion_periodo:
                characterization_parts.append(
                    "<h3>Discusión de grafos estimados</h3>"
                    "<div class='content-box'>"
                    "<h3 style='margin-top:0;'>Discusión de grafos estimados &mdash; período completo</h3>"
                    f"{_list_to_items(graph_discussion_periodo, max_items=max_conclusion_items)}"
                    "</div>"
                )
            characterization_parts.append("<h3>Grafos interactivos por escenario</h3>")
            characterization_parts.append(f"<div class='chart-grid'>{''.join(grafos_periodo)}</div>")

        critical_parts = []
        critical_sections = []
        critical_scenario_texts = []
        if puntos_criticos_frecuencia:
            text = _scenario_interpretation(puntos_criticos_frecuencia)
            if text:
                critical_scenario_texts.append(text)
                critical_sections.append(
                    "<h4>Número de Eventos</h4>"
                    + _text_to_items(text, max_items=max_conclusion_items)
                )
        if puntos_criticos_uiti:
            text = _scenario_interpretation(puntos_criticos_uiti)
            if text:
                critical_scenario_texts.append(text)
                critical_sections.append(
                    "<h4>UITI_VANO</h4>"
                    + _text_to_items(text, max_items=max_conclusion_items)
                )
        graph_discussion_criticos = _graph_discussion_items("puntos_criticos")
        hypothesis_criticos = _hypothesis_items("puntos_criticos", critical_scenario_texts, graph_discussion_criticos)
        if critical_sections:
            critical_parts.append(
                "<div class='summary-box'><h3 style='margin-top:0;'>Discusión de inferencias en puntos críticos</h3>"
                + "".join(critical_sections)
                + "</div>"
            )
        if hypothesis_criticos:
            critical_parts.append(
                "<div class='summary-box' style='background: #fffbeb; border-left: 5px solid #fbbf24;'>"
                "<h3 style='margin-top:0; color:#b45309;'>Hipótesis del modelo predictivo — puntos críticos</h3>"
                + _list_to_items(hypothesis_criticos, max_items=max_conclusion_items)
                + "</div>"
            )

        barras_criticos = []
        radares_criticos = []
        if puntos_criticos_frecuencia:
            barras_criticos.append(_chart_panel(
                "Número de eventos",
                _figure_html(puntos_criticos_frecuencia.get("fig_barras")),
            ))
            radares_criticos.append(_chart_panel(
                "Radar - Número de eventos",
                _figure_html(puntos_criticos_frecuencia.get("fig_radar")),
            ))
        if puntos_criticos_uiti:
            barras_criticos.append(_chart_panel(
                "Gravedad",
                _figure_html(puntos_criticos_uiti.get("fig_barras")),
            ))
            radares_criticos.append(_chart_panel(
                "Radar - Gravedad",
                _figure_html(puntos_criticos_uiti.get("fig_radar")),
            ))
        grafos_criticos = []
        if puntos_criticos_frecuencia:
            grafos_criticos.append(_graph_panel(
                "Grafo estimado - Número de eventos",
                puntos_criticos_frecuencia.get("grafo_interactivo"),
            ))
        if puntos_criticos_uiti:
            grafos_criticos.append(_graph_panel(
                "Grafo estimado - Gravedad",
                puntos_criticos_uiti.get("grafo_interactivo"),
            ))
        if barras_criticos or radares_criticos or grafos_criticos:
            critical_parts.insert(0, "<h2>Análisis de inferencias en puntos críticos</h2>")
        if barras_criticos:
            critical_parts.append("<h3>Barras por escenario</h3>")
            critical_parts.append(f"<div class='chart-grid two-col'>{''.join(barras_criticos)}</div>")
        if radares_criticos:
            critical_parts.append("<h3>Radares por escenario</h3>")
            critical_parts.append(f"<div class='chart-grid'>{''.join(radares_criticos)}</div>")
        if grafos_criticos:
            if graph_discussion_criticos:
                critical_parts.append(
                    "<h3>Discusión de grafos estimados</h3>"
                    "<div class='content-box'>"
                    "<h3 style='margin-top:0;'>Discusión de grafos estimados &mdash; puntos críticos</h3>"
                    f"{_list_to_items(graph_discussion_criticos, max_items=max_conclusion_items)}"
                    "</div>"
                )
            critical_parts.append("<h3>Grafos interactivos por escenario</h3>")
            critical_parts.append(f"<div class='chart-grid'>{''.join(grafos_criticos)}</div>")
        return "\n".join(characterization_parts), "\n".join(critical_parts)

    period_str = f"{start_date or 'Inicio'} a {end_date or 'Fin'}"
    title_str = f"Reporte Criticidad - Circuito: {primary_circuit}"

    # Adjust subtitle if no LLM data is present
    if validation_data:
        subtitle_info = f"Período de análisis: {period_str} | Modelo LLM: {llm_model}"
    else:
        subtitle_info = f"Período de análisis: {period_str} | (Solo visualización, sin análisis LLM)"

    title_html = f"Reporte Criticidad - Circuito: {primary_circuit}<br><span style='font-size: 0.6em; color: #64748b;'>{subtitle_info}</span>"

    map_panels = []
    if html_map_events:
        map_panels.append(_chart_panel("Mapa espacial GEO - Número de eventos", _iframe_srcdoc(html_map_events)))
    if html_map_uiti:
        map_panels.append(_chart_panel("Mapa espacial GEO - UITI_VANO", _iframe_srcdoc(html_map_uiti)))
    html_maps_section = f"<div class='chart-grid'>{''.join(map_panels)}</div>" if map_panels else ""

    html_inference_characterization, html_inference_critical = _render_inference_layout(inference_results, inference_analysis)
    characterization_visuals_html = f"{html_maps_section}{html_inference_characterization}"
    html_expert_alignment = render_expert_alignment_tab(
        expert_alignment_analysis,
        automatic_simulation_table=automatic_simulation_table,
        automatic_simulation_analysis=automatic_simulation_analysis,
        automatic_simulation_cost_context=automatic_simulation_cost_context,
        automatic_simulation_softmax_curves=automatic_simulation_softmax_curves,
        automatic_simulation_risk_maps_html=_simulator_risk_maps_html(),
    )

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
            top_percentile = char_data.get("top_vanos_percentile", 97)
            try:
                top_percentile_label = f"P{float(top_percentile):g}"
            except (TypeError, ValueError):
                top_percentile_label = "percentil configurado"

            p97_uiti = char_data.get('p97_vanos_uiti_vano', [])
            if p97_uiti:
                char_html += f"<h4>🔴 Top {top_percentile_label} Vanos (Mayor Gravedad UITI_VANO)</h4><ul>"
                for v in p97_uiti: char_html += f"<li>{v}</li>"
                char_html += "</ul>"

            p97_events = char_data.get('p97_vanos_eventos', [])
            if p97_events:
                char_html += f"<h4>🟠 Top {top_percentile_label} Vanos (Mayor Frecuencia de Eventos)</h4><ul>"
                for v in p97_events: char_html += f"<li>{v}</li>"
                char_html += "</ul>"

            justifications = char_data.get('probable_justifications_rules', [])
            if justifications:
                char_html += "<h4>🔗 Justificaciones Físico-Lógicas (Análisis por Modos)</h4><ul>"
                for j in justifications:
                    if isinstance(j, dict):
                        modo = j.get('modo', '')
                        vars_assoc = ", ".join(j.get('variables_asociadas', [])) if isinstance(j.get('variables_asociadas', []), list) else str(j.get('variables_asociadas', ''))
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
            <h2>⏱️ Síntesis del Periodo</h2>
            <div class="content-box">
                {_text_to_items(synthesis)}
            </div>
            """
    elif characterization_visuals_html:
        llm_sections_html = f"""
            <h2>📌 Caracterización del Circuito</h2>
            {characterization_visuals_html}
        """

    report_tab_html = f"""
            <div class="chart-container">{html_clusters}</div>

            {llm_sections_html}

            <h2>📈 Gráfica de Evaluación Diaria</h2>
            <div class="chart-container">{html_critical}</div>

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
            .container {{ max-width: 1200px; margin: auto; padding: 25px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
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
                        panel.classList.toggle('active', panel.id === targetId);
                    }});
                }});
            }});
        </script>
    </body>
    </html>
    """

    # Save to disk
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    start_str = start_date.strftime("%Y%m%d") if hasattr(start_date, 'strftime') else str(start_date).replace('-', '') if start_date else "inicio"
    end_str = end_date.strftime("%Y%m%d") if hasattr(end_date, 'strftime') else str(end_date).replace('-', '') if end_date else "fin"
    filename = f"{primary_circuit}_{start_str}_{end_str}_{timestamp}.html"
    filepath = Path(output_dir) / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    display(Markdown(f"✅ **Reporte generado y guardado exitosamente:** [{filepath.absolute()}]({filepath.absolute()})"))
    display(HTML(f'<a href="{filepath.absolute()}" target="_blank" style="display: inline-block; padding: 10px 20px; background-color: #2563eb; color: white; text-decoration: none; border-radius: 5px; font-weight: bold;">Abrir Reporte en Nueva Pestaña</a>'))

    return filepath
