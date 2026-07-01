from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from chec_local_interpreter.config import PROJECT_ROOT


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

    # Deduplicar por FECHA y FID_VANO si existen para evitar sobreconteo por múltiples equipos
    # if 'FECHA' in df.columns and 'FID_VANO' in df.columns:
    #     if not pd.api.types.is_datetime64_any_dtype(df['FECHA']):
    #         df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
    #     df = df.drop_duplicates(subset=['FECHA', 'FID_VANO'])

    # 1. Calculate the number of events per circuit and sort descending
    circuit_counts = df['CIRCUITO'].value_counts().sort_values(ascending=False)

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

    # Deduplicar por FECHA y FID_VANO si existen para evitar sobreconteo
    # if 'FECHA' in df.columns and 'FID_VANO' in df.columns:
    #     if not pd.api.types.is_datetime64_any_dtype(df['FECHA']):
    #         df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
    #     df = df.drop_duplicates(subset=['FECHA', 'FID_VANO'])

    # Calculate metrics per circuit
    counts = df['CIRCUITO'].value_counts()
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
            griddash='dot'
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor='#e2e8f0',
            gridwidth=1,
            griddash='dot'
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


def plot_circuit_map_plotly(df, circuito_name, date_range=None, color_target='number_of_events'):
    # 1. Filtrar por circuito
    df_filtered = df[df['CIRCUITO'] == circuito_name].copy()

    # 2. Filtrar por fechas
    if date_range is not None:
        df_filtered['FECHA_parsed'] = pd.to_datetime(df_filtered['FECHA'], errors='coerce')
        start_date = pd.to_datetime(date_range[0]) if date_range[0] else df_filtered['FECHA_parsed'].min()
        end_date = pd.to_datetime(date_range[1]) if date_range[1] else df_filtered['FECHA_parsed'].max()
        df_filtered = df_filtered[(df_filtered['FECHA_parsed'] >= start_date) &
                                  (df_filtered['FECHA_parsed'] <= end_date)]
    else:
        start_date, end_date = pd.to_datetime(df_filtered['FECHA']).min(), pd.to_datetime(df_filtered['FECHA']).max()

    geo_vanos = _load_geo_vanos_for_circuit(circuito_name)
    if geo_vanos is not None and 'FID_VANO' in df_filtered.columns:
        df_filtered['FID_VANO_NORM'] = _norm_map_id(df_filtered['FID_VANO'])
        df_filtered['UITI_VANO'] = pd.to_numeric(df_filtered['UITI_VANO'], errors='coerce').fillna(0)

        df_unique_events = df_filtered.copy()
        if color_target == 'number_of_events':
            vano_metrics = df_unique_events.groupby('FID_VANO_NORM').size().rename('metric_value')
            cbar_title = 'Número de Eventos'
        elif color_target == 'sum_uiti_vano' or color_target == 'UITI_VANO_sum':
            vano_metrics = df_unique_events.groupby('FID_VANO_NORM')['UITI_VANO'].sum().rename('metric_value')
            cbar_title = 'Suma de UITI_VANO'
        else:
            vano_metrics = df_unique_events.groupby('FID_VANO_NORM').size().rename('metric_value')
            cbar_title = 'Métrica Desconocida (Por Defecto: Eventos)'

        geo_plot = geo_vanos.merge(vano_metrics, left_on='FID_VANO_GEO', right_index=True, how='left')
        geo_plot['has_v3_event'] = geo_plot['metric_value'].notna()
        geo_plot['metric_value_color'] = geo_plot['metric_value'].fillna(0.0)

        colored_values = geo_plot.loc[geo_plot['has_v3_event'], 'metric_value_color']
        if colored_values.empty:
            print(f"No hay vanos de {circuito_name} con aparición en el archivo V3 para el periodo seleccionado.")
            vmin, vmax_robust = 0, 1
        else:
            vmin = colored_values.min()
            vmax_robust = np.percentile(colored_values, 95)
            if vmax_robust <= vmin:
                vmax_robust = colored_values.max()
                if vmax_robust == vmin:
                    vmax_robust = vmin + 1

        norm = mcolors.Normalize(vmin=vmin, vmax=vmax_robust)
        mapper = cm.ScalarMappable(norm=norm, cmap=cm.turbo)

        bounds = geo_plot.total_bounds
        center = {"lon": (bounds[0] + bounds[2]) / 2, "lat": (bounds[1] + bounds[3]) / 2}

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[center["lon"]], y=[center["lat"]], mode='markers',
            marker=dict(
                size=1,
                opacity=0,
                colorscale='Turbo', cmin=vmin, cmax=vmax_robust,
                colorbar=dict(title=dict(text=f"{cbar_title}<br>(Corte al p95)", font=dict(weight='bold')), thickness=15, len=0.8),
                color=[vmin],
                showscale=True
            ),
            showlegend=False, hoverinfo='none'
        ))

        for _, row in geo_plot.sort_values('has_v3_event').iterrows():
            val = row['metric_value_color']
            if row['has_v3_event']:
                color_rgba = mapper.to_rgba(val, bytes=True)
                line_color = f'#{color_rgba[0]:02x}{color_rgba[1]:02x}{color_rgba[2]:02x}'
                width = 4.5
                opacity = 0.9
                value_text = f"{val:.2f}"
            else:
                line_color = '#9ca3af'
                width = 2.0
                opacity = 0.45
                value_text = 'sin aparición en V3'

            hover_text = (
                f"FID VANO: {row['FID_VANO_GEO']}<br>"
                f"{cbar_title}: {value_text}"
            )
            for xs, ys in _iter_line_xy(row.geometry):
                fig.add_trace(go.Scatter(
                    x=xs,
                    y=ys,
                    mode='lines',
                    line=dict(color=line_color, width=width),
                    hoverinfo='text',
                    text=hover_text,
                    showlegend=False,
                    opacity=opacity
                ))

        fig.add_trace(go.Scatter(
            x=[None],
            y=[None],
            mode='lines',
            line=dict(color='#9ca3af', width=2),
            name='Sin aparición en V3',
            hoverinfo='none'
        ))

        total_metric = colored_values.sum() if not colored_values.empty else 0

        fig.update_layout(
            title=dict(text=f"Mapa de Red - Circuito: {circuito_name} (Total {cbar_title}: {total_metric:.2f})<br><sup>Periodo: {start_date} a {end_date} | Geometría: MVLINSEC</sup>", font=dict(size=18)),
            xaxis_title="Longitud",
            yaxis_title="Latitud",
            yaxis=dict(scaleanchor="x", scaleratio=1),
            plot_bgcolor='#f8fafc',
            paper_bgcolor='#ffffff',
            width=1000,
            height=800,
            margin=dict(l=60, r=50, t=90, b=80),
            legend=dict(title="Vanos", yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(255, 255, 255, 0.8)")
        )
        return fig


    coords_cols = ['X1', 'Y1', 'X2', 'Y2']
    df_filtered = df_filtered.dropna(subset=coords_cols)
    if df_filtered.empty:
        print(f"No hay coordenadas válidas para {circuito_name}.")
        return

    for col in coords_cols:
        df_filtered[col] = pd.to_numeric(df_filtered[col], errors='coerce')
    df_filtered = df_filtered.dropna(subset=coords_cols)
    df_filtered['UITI_VANO'] = pd.to_numeric(df_filtered['UITI_VANO'], errors='coerce').fillna(0)

    # Deduplicar por evento (vano + fecha) para evitar sobreconteo por múltiples equipos (TIPO)
    # if 'FECHA' in df_filtered.columns and not pd.api.types.is_datetime64_any_dtype(df_filtered['FECHA']):
    #     df_filtered['FECHA'] = pd.to_datetime(df_filtered['FECHA'], errors='coerce')
    # df_unique_events = df_filtered.drop_duplicates(subset=['FID_VANO', 'FECHA'])
    df_unique_events = df_filtered.copy()

    # 3. Calcular la métrica (usando el dataset deduplicado)
    if color_target == 'number_of_events':
        vano_metrics = df_unique_events.groupby('FID_VANO').size().to_dict()
        cbar_title = 'Número de Eventos'
    elif color_target == 'sum_uiti_vano' or color_target == 'UITI_VANO_sum':
        vano_metrics = df_unique_events.groupby('FID_VANO')['UITI_VANO'].sum().to_dict()
        cbar_title = 'Suma de UITI_VANO'
    else:
        vano_metrics = df_unique_events.groupby('FID_VANO').size().to_dict()
        cbar_title = 'Métrica Desconocida (Por Defecto: Eventos)'

    df_filtered['metric_value'] = df_filtered['FID_VANO'].map(vano_metrics)
    df_lines = df_filtered.drop_duplicates(subset=['FID_VANO']).copy()

    # ==========================================
    # MEJORA DE VISIBILIDAD: Escala Robusta
    # ==========================================
    vmin = df_lines['metric_value'].min()
    # Usar el percentil 95 o 98 evita que 1 vano atípico arruine todo el contraste de colores
    vmax_robust = np.percentile(df_lines['metric_value'], 95)

    # Si todos los valores son iguales, ajustamos
    if vmax_robust <= vmin:
        vmax_robust = df_lines['metric_value'].max()
        if vmax_robust == vmin:
            vmax_robust = vmin + 1

    norm = mcolors.Normalize(vmin=vmin, vmax=vmax_robust)
    mapper = cm.ScalarMappable(norm=norm, cmap=cm.turbo) # 'turbo' tiene el mejor contraste

    fig = go.Figure()

    # Colorbar
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode='markers',
        marker=dict(
            colorscale='Turbo', cmin=vmin, cmax=vmax_robust,
            colorbar=dict(title=dict(text=f"{cbar_title}<br>(Corte al p95)", font=dict(weight='bold')), thickness=15, len=0.8),
            showscale=True
        ),
        showlegend=False, hoverinfo='none'
    ))

    # ==========================================
    # MEJORA DE VISIBILIDAD: Líneas más gruesas
    # ==========================================
    for _, row in df_lines.iterrows():
        val = row['metric_value']
        color_rgba = mapper.to_rgba(val, bytes=True)
        hex_color = f'#{color_rgba[0]:02x}{color_rgba[1]:02x}{color_rgba[2]:02x}'

        # Make sure we don't throw an error if TIPO is missing somehow
        tipo_val = row['TIPO'] if 'TIPO' in row else 'N/A'

        fig.add_trace(go.Scatter(
            x=[row['X1'], row['X2']],
            y=[row['Y1'], row['Y2']],
            mode='lines',
            line=dict(color=hex_color, width=4.5), # Línea más gruesa (4.5)
            hoverinfo='text',
            text=f"FID_VANO: {row['FID_VANO']}<br>TIPO: {tipo_val}<br>{cbar_title}: {val:.2f}",
            showlegend=False,
            opacity=0.9
        ))

    # ==========================================
    # MEJORA DE VISIBILIDAD: Puntos más discretos
    # ==========================================
    df_points = df_filtered.drop_duplicates(subset=['X1', 'Y1', 'TIPO']).copy()
    tipos = df_points['TIPO'].unique()
    symbols_px = ['circle', 'square', 'diamond', 'cross', 'x', 'triangle-up', 'triangle-down', 'pentagon', 'hexagon', 'star']

    for i, tipo in enumerate(tipos):
        dft = df_points[df_points['TIPO'] == tipo]
        fig.add_trace(go.Scatter(
            x=dft['X1'], y=dft['Y1'],
            mode='markers',
            marker=dict(
                size=8,
                opacity=0.9,
                symbol=symbols_px[i % len(symbols_px)],
                color=dft['metric_value'],
                colorscale='Turbo',
                cmin=vmin,
                cmax=vmax_robust,
                showscale=False,
                line=dict(width=0.5, color='white')
            ),
            name=f"TIPO: {tipo}",
            hoverinfo='text',
            text=dft.apply(lambda r: f"FID_VANO: {r['FID_VANO']}<br>TIPO: {r['TIPO']}<br>{cbar_title}: {r['metric_value']:.2f}", axis=1)
        ))

    total_metric = df_lines['metric_value'].sum()

    fig.update_layout(
        title=dict(text=f"Mapa de Red - Circuito: {circuito_name} (Total {cbar_title}: {total_metric:.2f})<br><sup> Periodo: {start_date} a {end_date} </sup>", font=dict(size=18)),
        xaxis_title="Coordenada X (Este)",
        yaxis_title="Coordenada Y (Norte)",
        #plot_bgcolor='#2b3035', # Fondo oscuro opcional para que los colores brillen más (ajusta si prefieres claro)
        yaxis=dict(scaleanchor="x", scaleratio=1),
        width=1000, height=800,
        legend=dict(title="Equipos (TIPO)", yanchor="top", y=0.99, xanchor="right", x=0.01, bgcolor="rgba(255, 255, 255, 0.8)")
    )

    return fig

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


def render_expert_alignment_tab(expert_alignment_validation_data):
    """
    Renderiza la segunda pestaña del reporte HTML con la comparación
    entre el agente de análisis histórico, el agente del modelo predictivo y reportes expertos.
    No devuelve JSON crudo; solo HTML escapado con las clases visuales del reporte.
    """
    import html

    analysis = expert_alignment_validation_data if isinstance(expert_alignment_validation_data, dict) else None

    def _escape(text):
        return html.escape("" if text is None else str(text))

    def _value(value):
        source_labels = {
            "LLM1": "Agente base",
            "LLM2": "Agente predictivo",
            "LLM de datos históricos": "Agente base",
            "LLM del modelo predictivo": "Agente predictivo",
            "agente de análisis histórico": "Agente base",
            "agente del modelo predictivo": "Agente predictivo",
            "PDF_EXPERTO": "reportes expertos",
        }
        if isinstance(value, list):
            return ", ".join(_escape(source_labels.get(str(item), str(item))) for item in value if str(item).strip())
        return _escape(source_labels.get(str(value), value))

    def _empty_message():
        return "<p class='muted'>No hay elementos reportados para esta sección.</p>"

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

    if not analysis:
        return (
            "<div class='summary-box'>"
            "<h2 style='margin-top:0;'>Comparación con reportes expertos</h2>"
            "<p>La comparación con reportes expertos no está disponible para esta ejecución.</p>"
            "</div>"
        )

    contexto = analysis.get("contexto", {}) if isinstance(analysis.get("contexto"), dict) else {}
    periodo = contexto.get("periodo", {}) if isinstance(contexto.get("periodo"), dict) else {}
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
        "<h2>Comparación con reportes expertos</h2>"
        "<div class='summary-box'>"
        "<h3 style='margin-top:0;'>Resumen de la comparación</h3>"
        f"{resumen}"
        "</div>"
        + _finding_items(
            "coincidencias",
            "Coincidencias entre análisis histórico, modelo predictivo y reportes expertos",
        )
        + _finding_items(
            "diferencias",
            "Diferencias entre análisis histórico, modelo predictivo y reportes expertos",
        )
        + _variables_table()
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

    fig_map_events = None
    fig_map_uiti = None
    if primary_circuit != "TODOS":
        fig_map_events = plot_circuit_map_plotly(raw_df, primary_circuit, date_range=(start_date, end_date) if start_date and end_date else None, color_target='number_of_events')
        fig_map_uiti = plot_circuit_map_plotly(raw_df, primary_circuit, date_range=(start_date, end_date) if start_date and end_date else None, color_target='sum_uiti_vano')
        if fig_map_events:
            fig_map_events.update_layout(
                title=dict(text=f"Mapa de red - {primary_circuit} (Número de eventos)", font=dict(size=14)),
                margin=dict(t=55),
            )
        if fig_map_uiti:
            fig_map_uiti.update_layout(
                title=dict(text=f"Mapa de red - {primary_circuit} (Gravedad)", font=dict(size=14)),
                margin=dict(t=55),
            )

    # Convert figures to HTML snippets
    html_events = fig_events.to_html(full_html=False, include_plotlyjs='cdn') if fig_events else ""
    html_sums = fig_sums.to_html(full_html=False, include_plotlyjs='cdn') if fig_sums else ""
    html_clusters = fig_clusters.to_html(full_html=False, include_plotlyjs='cdn') if fig_clusters else ""
    html_critical = fig_critical.to_html(full_html=False, include_plotlyjs='cdn') if fig_critical else ""
    html_map_events = fig_map_events.to_html(full_html=False, include_plotlyjs='cdn') if fig_map_events else ""
    html_map_uiti = fig_map_uiti.to_html(full_html=False, include_plotlyjs='cdn') if fig_map_uiti else ""

    def _escape(text):
        import html
        return html.escape("" if text is None else str(text))

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
    if fig_map_events:
        map_panels.append(_chart_panel("Mapa espacial - Número de eventos", html_map_events))
    if fig_map_uiti:
        map_panels.append(_chart_panel("Mapa espacial - Gravedad", html_map_uiti))
    html_maps_section = f"<div class='chart-grid'>{''.join(map_panels)}</div>" if map_panels else ""

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
