from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd


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

def plot_circuit_map_plotly(df, circuito_name, date_range=None, color_target='number_of_events'):
    # 1. Filtrar por circuito
    df_filtered = df[df['CIRCUITO'] == circuito_name].copy()
    
    # 2. Filtrar por fechas
    if date_range is not None:
        df_filtered['FECHA_parsed'] = pd.to_datetime(df_filtered['FECHA'], errors='coerce')
        start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
        df_filtered = df_filtered[(df_filtered['FECHA_parsed'] >= start_date) & 
                                  (df_filtered['FECHA_parsed'] <= end_date)]
    else:
        start_date, end_date = pd.to_datetime(df_filtered['FECHA']).min(), pd.to_datetime(df_filtered['FECHA']).max()                             
    
        
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
        
        fig.add_trace(go.Scatter(
            x=[row['X1'], row['X2']],
            y=[row['Y1'], row['Y2']],
            mode='lines',
            line=dict(color=hex_color, width=4.5), # Línea más gruesa (4.5)
            hoverinfo='text',
            text=f"FID_VANO: {row['FID_VANO']}<br>{cbar_title}: {val:.2f}",
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
            text=dft.apply(lambda r: f"TIPO: {r['TIPO']}<br>{cbar_title}: {r['metric_value']:.2f}", axis=1)
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
    
    fig.show()

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


def render_llm_analysis(
    validation_data: dict,
    raw_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    critical_points: list[dict],
    selected_circuitos: list[str],
    start_date: str = None,
    end_date: str = None,
    output_dir: str | Path = "notebooks/outputs"
):
    """
    Renders the structured JSON output from the LLM into a beautiful HTML format
    suitable for Jupyter Notebooks, incorporating interactive Plotly charts.
    """
    from IPython.display import display, Markdown, HTML
    from datetime import datetime
    import os
    
    if not validation_data:
        display(Markdown("> **No hay un diagnóstico válido disponible para renderizar.**"))
        return
        
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

    # Convert figures to HTML snippets
    html_events = fig_events.to_html(full_html=False, include_plotlyjs='cdn') if fig_events else ""
    html_sums = fig_sums.to_html(full_html=False, include_plotlyjs='cdn') if fig_sums else ""
    html_clusters = fig_clusters.to_html(full_html=False, include_plotlyjs='cdn') if fig_clusters else ""
    html_critical = fig_critical.to_html(full_html=False, include_plotlyjs='cdn') if fig_critical else ""
    html_map_events = fig_map_events.to_html(full_html=False, include_plotlyjs='cdn') if fig_map_events else ""
    html_map_uiti = fig_map_uiti.to_html(full_html=False, include_plotlyjs='cdn') if fig_map_uiti else ""

    # Parse key findings
    kf_html = ""
    for kf in validation_data.get('key_findings', []):
        if isinstance(kf, dict):
            title = kf.get('title', 'Hallazgo')
            text = kf.get('text', '')
            kf_html += f'<li style="margin-bottom: 10px;"><strong>{title}:</strong> {text}</li>'
        else:
            kf_html += f'<li style="margin-bottom: 10px;">{kf}</li>'

    period_str = f"{start_date or 'Inicio'} a {end_date or 'Fin'}"
    title_str = f"Reporte Criticidad {primary_circuit}"
    title_html = f"Reporte Criticidad {primary_circuit}<br><span style='font-size: 0.6em; color: #64748b;'>Período de análisis: {period_str}</span>"

    exec_summary = validation_data.get('executive_summary', [])
    if isinstance(exec_summary, list):
        exec_summary = " ".join(exec_summary)

    # Parse circuit characterization
    char_data = validation_data.get('circuit_characterization', {})
    if isinstance(char_data, dict):
        char_text = char_data.get('text', '')
        
        char_html = f"<p>{char_text}</p>"
        
        p97_uiti = char_data.get('p97_vanos_uiti_vano', [])
        if p97_uiti:
            char_html += "<h4>🔴 Top 97% Vanos (Mayor Gravedad UITI_VANO)</h4><ul>"
            for v in p97_uiti: char_html += f"<li>{v}</li>"
            char_html += "</ul>"
            
        p97_events = char_data.get('p97_vanos_eventos', [])
        if p97_events:
            char_html += "<h4>🟠 Top 97% Vanos (Mayor Frecuencia de Eventos)</h4><ul>"
            for v in p97_events: char_html += f"<li>{v}</li>"
            char_html += "</ul>"
            
        justifications = char_data.get('probable_justifications_rules', [])
        if justifications:
            char_html += "<h4>🔗 Justificaciones Físico-Lógicas (Análisis por Modos)</h4><ul>"
            for j in justifications:
                if isinstance(j, dict):
                    rel = j.get('relacion_descriptiva', '')
                    ana = j.get('analisis_causas', '')
                    char_html += f"<li style='margin-bottom: 8px;'><strong>{rel}</strong><br><span style='font-size: 0.95em; color: #475569;'>{ana}</span></li>"
                else:
                    char_html += f"<li>{j}</li>"
            char_html += "</ul>"
    else:
        char_html = str(char_data)

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
            h4 {{ color: #334155; margin-bottom: 5px; margin-top: 15px; }}
            .summary-box {{ background: #eff6ff; padding: 15px; border-left: 5px solid #3b82f6; border-radius: 6px; margin-bottom: 20px; }}
            .content-box {{ background: #ffffff; padding: 15px; border: 1px solid #cbd5e1; border-radius: 6px; line-height: 1.6; margin-bottom: 20px; }}
            .chart-container {{ margin-bottom: 40px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 {title_html}</h1>
            
            <div class="chart-container">{html_clusters}</div>
            
            <div class="summary-box">
                <h2 style="margin-top: 0;">Resumen Ejecutivo</h2>
                <p>{exec_summary}</p>
            </div>

            <h2>📌 Caracterización del Circuito</h2>
            <div class="content-box">
                {char_html}
            </div>

            <h2>⏱️ Síntesis del Periodo</h2>
            <div class="content-box">
                {validation_data.get('period_synthesis', '')}
            </div>
            
            <h2>🔍 Hallazgos Clave Descriptivos</h2>
            <ul class="content-box" style="padding-left: 35px;">
                {kf_html}
            </ul>

            <h2>📈 Gráfica de Evaluación Diaria</h2>
            <div class="chart-container">{html_critical}</div>
            """
            
    if fig_map_events:
        html_content += f"<h2>🗺️ Mapa Espacial: Número de Eventos</h2><div class='chart-container'>{html_map_events}</div>"
    if fig_map_uiti:
        html_content += f"<h2>🗺️ Mapa Espacial: Gravedad (UITI_VANO)</h2><div class='chart-container'>{html_map_uiti}</div>"

    html_content += f"""
        </div>
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
