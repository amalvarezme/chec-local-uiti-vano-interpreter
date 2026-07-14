from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from chec_local_interpreter.data.loader import numeric_series, resolve_column, text_series
from chec_local_interpreter.analysis.domain_context import VARIABLE_GROUPS


def _date_filter(events_df: pd.DataFrame, date: str) -> pd.DataFrame:
    if events_df.empty:
        return events_df.copy()
    work = events_df.copy()
    if "fecha_dia" not in work.columns:
        fecha_column = resolve_column(work, "FECHA")
        if fecha_column is None:
            return pd.DataFrame()
        work["fecha_dia"] = pd.to_datetime(work[fecha_column], errors="coerce").dt.floor("D")
    dates = pd.to_datetime(work["fecha_dia"], errors="coerce").dt.date.astype(str)
    return work[dates == str(date)].copy()


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def top_labels_for_day(
    events_df: pd.DataFrame,
    date: str,
    column: str,
    weight_column: str = "UITI_VANO",
    limit: int = 3,
) -> list[dict[str, Any]]:
    day = _date_filter(events_df, date)
    resolved = resolve_column(day, column)
    if day.empty or resolved is None:
        return []
    weights = numeric_series(day, [weight_column], default=0.0)
    labels = day[resolved].fillna("Sin dato").astype(str).str.strip().replace("", "Sin dato")
    work = pd.DataFrame({"label": labels, "weight": weights})
    grouped = (
        work.groupby("label", dropna=False)
        .agg(event_count=("label", "size"), total_weight=("weight", "sum"))
        .reset_index()
        .sort_values(["total_weight", "event_count", "label"], ascending=[False, False, True])
        .head(limit)
    )
    return [
        {
            str(row["label"])[:30]: int(row["event_count"])
        }
        for _, row in grouped.iterrows()
    ]


def top_events_for_day(events_df: pd.DataFrame, date: str, limit: int = 2) -> list[dict[str, Any]]:
    day = _date_filter(events_df, date)
    if day.empty:
        return []
    work = day.copy()
    work["_UITI_VANO"] = numeric_series(work, ["UITI_VANO"])
    work["_DURACION"] = numeric_series(work, ["DURACION"])
    work["_USERS"] = numeric_series(work, ["TOT_USUS", "CNT_USUS"])
    work = work.sort_values(["_UITI_VANO", "_DURACION", "_USERS"], ascending=[False, False, False]).head(limit)
    fields = [
        "FID_VANO",
        "DESC_CAUSA",
        "UITI_VANO",
    ]
    rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        item: dict[str, Any] = {}
        for field in fields:
            column = resolve_column(work, field)
            if column is not None:
                val = _json_value(row.get(column))
                if isinstance(val, float):
                    val = round(val, 1)
                item[field] = val
        rows.append(item)
    return rows


def _weather_columns(events_df: pd.DataFrame) -> dict[str, list[str]]:
    families = {
        "precip": ("PREP",),
        "wind": ("WIND_SPD",),
        "gust": ("WIND_GUST_SPD",),
        "temp": ("TEMP",),
    }
    columns_by_upper = {str(column).upper(): str(column) for column in events_df.columns}
    detected: dict[str, list[str]] = {}
    for family, prefixes in families.items():
        cols: list[str] = []
        for upper, original in columns_by_upper.items():
            if any(upper.startswith(f"{prefix}_") for prefix in prefixes):
                cols.append(original)
        detected[family] = sorted(cols, key=lambda item: item.upper())
    return detected


def _family_stats(frame: pd.DataFrame, columns: list[str], family: str) -> dict[str, Any]:
    if not columns:
        return {}
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    flat = values.stack().dropna()
    if flat.empty:
        return {}
    if family == "precip":
        return {"sum": round(float(flat.sum()), 1), "max": round(float(flat.max()), 1)}
    elif family in {"wind", "gust"}:
        return {"max": round(float(flat.max()), 1), "mean": round(float(flat.mean()), 1)}
    elif family == "temp":
        return {"min": round(float(flat.min()), 1), "max": round(float(flat.max()), 1)}
    return {"mean": round(float(flat.mean()), 1)}


def summarize_weather_for_day(events_df: pd.DataFrame, date: str) -> dict[str, Any]:
    day = _date_filter(events_df, date)
    if day.empty:
        return {}
    detected = _weather_columns(day)
    result = {}
    for family, columns in detected.items():
        if columns:
            stats = _family_stats(day, columns, family)
            if stats:
                result[family] = stats
    return result



def enrich_critical_points(events_df: pd.DataFrame, critical_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for point in critical_points:
        date = str(point["fecha_dia"])
        copy = dict(point)
        copy["attr"] = {
            "causes": top_labels_for_day(events_df, date, "DESC_CAUSA")
            or top_labels_for_day(events_df, date, "COD_CAUSA"),
            "vanos": top_labels_for_day(events_df, date, "FID_VANO"),
            "top_rows": top_events_for_day(events_df, date),
            "weather": summarize_weather_for_day(events_df, date),
        }
        enriched.append(copy)
    return enriched
