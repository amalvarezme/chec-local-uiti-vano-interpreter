from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np

import pandas as pd

from chec_local_interpreter.config import PROMPT_VERSION, SCHEMA_VERSION
from chec_local_interpreter.data_loader import resolve_columns
from chec_local_interpreter.domain_context import domain_context_payload


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _safe_float(value: Any) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return 0.0
    return round(float(numeric), 2)


def daily_series_records(daily_df: pd.DataFrame, limit: int = 60) -> list[dict[str, Any]]:
    """Return compact daily records for the LLM context.
    
    Only includes days with non-zero UITI_VANO to save tokens.
    Caps at `limit` records (sorted by UITI_VANO descending so the
    most important days are always included).
    """
    if daily_df.empty:
        return []
    work = daily_df.copy()
    work["_uv"] = pd.to_numeric(work.get("UITI_VANO", 0), errors="coerce").fillna(0)
    # Keep only non-zero days
    work = work[work["_uv"] > 0].sort_values("_uv", ascending=False).head(limit)
    # Re-sort by date for chronological context
    work = work.sort_values("fecha_dia")
    records: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        records.append({
            "d": _date_text(row.get("fecha_dia")),
            "uv": _safe_float(row.get("UITI_VANO")),
            "n": int(row.get("event_count") or 0),
            "dur": _safe_float(row.get("DURACION_total")),
        })
    return records


def window_summary(events_df: pd.DataFrame, daily_df: pd.DataFrame) -> dict[str, Any]:
    if daily_df.empty:
        return {
            "events": int(len(events_df)),
            "nonzero_days": 0,
            "total_uv": 0.0,
        }
    values = pd.to_numeric(daily_df.get("UITI_VANO", 0.0), errors="coerce").fillna(0.0)
    max_index = values.idxmax() if not values.empty else None
    return {
        "events": int(len(events_df)),
        "nonzero_days": int((values > 0).sum()),
        "total_uv": _safe_float(values.sum()),
        "max_date": None if max_index is None else _date_text(daily_df.loc[max_index, "fecha_dia"]),
        "max_uv": 0.0 if max_index is None else _safe_float(values.loc[max_index]),
    }


def build_context_package(
    *,
    events_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    critical_points: list[dict[str, Any]],
    critical_periods: list[dict[str, Any]],
    selected_circuitos: list[str],
    start_date: str | None,
    end_date: str | None,
    raw_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    resolution = resolve_columns(events_df) if not events_df.empty else None
    unavailable = resolution.unavailable_optional if resolution is not None else []
    try:
        from chec_local_interpreter.graph_extractor import build_graphify_context
        graph_summary = build_graphify_context(raw_df if raw_df is not None else events_df, "_".join(selected_circuitos))
    except Exception as e:
        graph_summary = f"Grafo no disponible: {e}"

    context = {
        "analysis_name": "local_uiti_vano_interpretability",
        "metadata": {
            "v": PROMPT_VERSION,
            "schema": SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
            "circuitos": selected_circuitos,
            "start": _date_text(start_date) if start_date else None,
            "end": _date_text(end_date) if end_date else None,
            "unavailable_cols": unavailable,
        },
        "selected_context": {
            "circuitos": selected_circuitos,
            "indicator": "UITI_VANO",
            "characterization": _compute_circuit_characterization(
                raw_df if raw_df is not None else events_df, selected_circuitos
            ),
        },
        "summary": window_summary(events_df, daily_df),
        "daily": daily_series_records(daily_df),
        "critical_points": critical_points,
        "critical_periods": critical_periods,
        "domain": domain_context_payload(),
        "graph_knowledge": graph_summary,
    }
    return context


def save_json_artifact(payload: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _compute_circuit_characterization(df: pd.DataFrame, selected_circuitos: list[str]) -> list[dict[str, Any]]:
    if df.empty or not selected_circuitos:
        return []
        
    df_copy = df.copy()
    if 'UITI_VANO' not in df_copy.columns or 'CIRCUITO' not in df_copy.columns:
        return []
        
    df_copy['UITI_VANO'] = pd.to_numeric(df_copy['UITI_VANO'], errors='coerce').fillna(0.0)
    
    counts = df_copy['CIRCUITO'].value_counts()
    sums = df_copy.groupby('CIRCUITO')['UITI_VANO'].sum()
    
    df_coords = pd.DataFrame({
        'event_count': counts,
        'uiti_vano_sum': sums
    }).dropna()
    
    if df_coords.empty:
        return []
        
    X = df_coords[['event_count', 'uiti_vano_sum']].astype(float).values
    X_mean = X.mean(axis=0)
    X_std = np.where(X.std(axis=0) == 0, 1e-9, X.std(axis=0)) 
    X_scaled = (X - X_mean) / X_std

    try:
        from chec_local_interpreter.plotting import run_kmeans
        n_clusters = min(4, len(df_coords))
        df_coords['cluster'] = run_kmeans(X_scaled, n_clusters=n_clusters, random_state=42)
        
        cluster_scores = {}
        for cluster_id in range(n_clusters):
            cluster_mask = df_coords['cluster'] == cluster_id
            cluster_scores[cluster_id] = X_scaled[cluster_mask].mean()
            
        sorted_clusters = sorted(cluster_scores.keys(), key=lambda c: cluster_scores[c], reverse=True)
        group_labels = ["Muy Alta", "Alta", "Media", "Baja"]
    except ImportError:
        df_coords['cluster'] = 0
        sorted_clusters = [0]
        group_labels = ["Desconocido"]
        
    global_avg_events = counts.mean()
    global_avg_uiti = sums.mean()
    
    df_coords_sorted = df_coords.sort_values(by='uiti_vano_sum', ascending=False)
    circuits_to_process = [c for c in df_coords_sorted.index if c in selected_circuitos][:5]
    
    results = []
    for circuito in circuits_to_process:
        if circuito in df_coords.index:
            row = df_coords.loc[circuito]
            cluster_id = row['cluster']
            rank = sorted_clusters.index(cluster_id) if cluster_id in sorted_clusters else 0
            label = group_labels[rank] if rank < len(group_labels) else "Desconocida"
            
            # Compute P97 vanos (top 3% most critical)
            df_circuito = df_copy[df_copy['CIRCUITO'] == circuito]
            p97_uiti_list = []
            p97_events_list = []
            if not df_circuito.empty and 'FID_VANO' in df_circuito.columns:
                vano_stats = df_circuito.groupby('FID_VANO').agg(
                    events=('FID_VANO', 'count'),
                    uiti_sum=('UITI_VANO', 'sum')
                )
                if not vano_stats.empty:
                    try:
                        p97_uiti = vano_stats['uiti_sum'].quantile(0.97)
                        p97_events = vano_stats['events'].quantile(0.97)
                        
                        top_uiti_vanos = vano_stats[vano_stats['uiti_sum'] >= p97_uiti].sort_values('uiti_sum', ascending=False)
                        top_events_vanos = vano_stats[vano_stats['events'] >= p97_events].sort_values('events', ascending=False)
                        
                        p97_uiti_list = [f"{fid}(U:{r['uiti_sum']:.0f})" for fid, r in top_uiti_vanos.iterrows()][:5]
                        p97_events_list = [f"{fid}(E:{r['events']})" for fid, r in top_events_vanos.iterrows()][:5]
                    except Exception:
                        p97_uiti_list = []
                        p97_events_list = []

            results.append({
                "circuito": circuito,
                "criticidad": label,
                "eventos": int(row['event_count']),
                "uiti_vano_total": round(float(row['uiti_vano_sum']), 0),
                "avg_eventos_red": round(float(global_avg_events), 0),
                "avg_uiti_red": round(float(global_avg_uiti), 0),
                "p97_uiti": p97_uiti_list,
                "p97_eventos": p97_events_list,
            })
            
    return results



def critical_points_frame(critical_points: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for point in critical_points:
        rows.append(
            {
                "critical_point_id": point.get("critical_point_id"),
                "fecha_dia": point.get("fecha_dia"),
                "rank": point.get("rank"),
                "score": point.get("score"),
                "types": ";".join(point.get("types") or []),
                "selection_reason": point.get("selection_reason"),
                "UITI_VANO": (point.get("metrics") or {}).get("UITI_VANO"),
                "events": (point.get("daily_aggregates") or {}).get("events"),
            }
        )
    return pd.DataFrame(rows)

