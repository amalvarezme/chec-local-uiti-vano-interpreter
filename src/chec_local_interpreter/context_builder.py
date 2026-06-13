from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
            "start_date": start_date,
            "end_date": end_date,
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
            "start_date": start_date,
            "end_date": end_date,
            "indicator": "UITI_VANO",
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
