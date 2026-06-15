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
    return round(float(numeric), 4)


def daily_series_records(daily_df: pd.DataFrame, limit: int = 500) -> list[dict[str, Any]]:
    if daily_df.empty:
        return []
    records: list[dict[str, Any]] = []
    for _, row in daily_df.head(limit).iterrows():
        records.append(
            {
                "fecha_dia": _date_text(row.get("fecha_dia")),
                "UITI_VANO": _safe_float(row.get("UITI_VANO")),
                "event_count": int(row.get("event_count") or 0),
                "DURACION_total": _safe_float(row.get("DURACION_total")),
                "users_total": _safe_float(row.get("users_total")),
                "UITI": _safe_float(row.get("UITI")),
            }
        )
    return records


def window_summary(events_df: pd.DataFrame, daily_df: pd.DataFrame) -> dict[str, Any]:
    if daily_df.empty:
        return {
            "row_count": int(len(events_df)),
            "event_count": int(len(events_df)),
            "nonzero_days": 0,
            "total_uiti_vano": 0.0,
            "max_uiti_vano_date": None,
            "max_uiti_vano_value": 0.0,
        }
    values = pd.to_numeric(daily_df.get("UITI_VANO", 0.0), errors="coerce").fillna(0.0)
    max_index = values.idxmax() if not values.empty else None
    return {
        "row_count": int(len(events_df)),
        "event_count": int(len(events_df)),
        "nonzero_days": int((values > 0).sum()),
        "total_uiti_vano": _safe_float(values.sum()),
        "max_uiti_vano_date": None if max_index is None else _date_text(daily_df.loc[max_index, "fecha_dia"]),
        "max_uiti_vano_value": 0.0 if max_index is None else _safe_float(values.loc[max_index]),
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
    context = {
        "analysis_name": "local_uiti_vano_interpretability",
        "metadata": {
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "row_count": int(len(events_df)),
            "daily_row_count": int(len(daily_df)),
            "selected_circuitos": selected_circuitos,
            "start_date": _date_text(start_date) if start_date else None,
            "end_date": _date_text(end_date) if end_date else None,
            "unavailable_optional_columns": unavailable,
        },
        "flow_scope": {
            "included_steps": [1, 2, 3],
            "excluded_steps": [
                "RAG",
                "bitacoras",
                "normativa",
                "modelo_predictivo",
                "mascaras_relevancia",
                "what_if",
                "reporte_final",
            ],
        },
        "selected_context": {
            "circuitos": selected_circuitos,
            "start_date": _date_text(start_date) if start_date else None,
            "end_date": _date_text(end_date) if end_date else None,
            "indicator": "UITI_VANO",
            "circuit_characterization": _compute_circuit_characterization(raw_df if raw_df is not None else events_df, selected_circuitos),
        },
        "window_summary": window_summary(events_df, daily_df),
        "daily_series": daily_series_records(daily_df),
        "critical_points": critical_points,
        "critical_periods": critical_periods,
        "domain_context": domain_context_payload(),
        "guardrails": {
            "do_not_detect_new_points": True,
            "do_not_claim_definitive_causality": True,
            "do_not_use_rag_or_normative_evidence": True,
            "use_only_structured_data_and_domain_context": True,
        },
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
    
    results = []
    for circuito in selected_circuitos:
        if circuito in df_coords.index:
            row = df_coords.loc[circuito]
            cluster_id = row['cluster']
            rank = sorted_clusters.index(cluster_id) if cluster_id in sorted_clusters else 0
            label = group_labels[rank] if rank < len(group_labels) else "Desconocida"
            results.append({
                "circuito": circuito,
                "criticidad_global_kmeans": label,
                "eventos_historicos": int(row['event_count']),
                "uiti_vano_historico": round(float(row['uiti_vano_sum']), 2),
                "promedio_global_eventos_red": round(float(global_avg_events), 2),
                "promedio_global_uiti_red": round(float(global_avg_uiti), 2)
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
                "criticality_score": point.get("criticality_score"),
                "criticality_types": ";".join(point.get("criticality_types") or []),
                "selection_reason": point.get("selection_reason"),
                "UITI_VANO": (point.get("metrics") or {}).get("UITI_VANO"),
                "event_count": (point.get("daily_aggregates") or {}).get("event_count"),
            }
        )
    return pd.DataFrame(rows)
