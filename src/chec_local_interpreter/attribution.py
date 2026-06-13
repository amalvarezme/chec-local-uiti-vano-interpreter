from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from chec_local_interpreter.data_loader import numeric_series, resolve_column, text_series
from chec_local_interpreter.domain_context import VARIABLE_GROUPS


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
    limit: int = 5,
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
            "label": str(row["label"]),
            "event_count": int(row["event_count"]),
            "total_uiti_vano": round(float(row["total_weight"]), 4),
        }
        for _, row in grouped.iterrows()
    ]


def top_events_for_day(events_df: pd.DataFrame, date: str, limit: int = 10) -> list[dict[str, Any]]:
    day = _date_filter(events_df, date)
    if day.empty:
        return []
    work = day.copy()
    work["_UITI_VANO"] = numeric_series(work, ["UITI_VANO"])
    work["_DURACION"] = numeric_series(work, ["DURACION"])
    work["_USERS"] = numeric_series(work, ["TOT_USUS", "CNT_USUS"])
    work = work.sort_values(["_UITI_VANO", "_DURACION", "_USERS"], ascending=[False, False, False]).head(limit)
    fields = [
        "CIRCUITO",
        "FID_VANO",
        "DESC_CAUSA",
        "COD_CAUSA",
        "FID_SW",
        "COD_EQ_PROTEGE",
        "TIPO",
        "DURACION",
        "TOT_USUS",
        "CNT_USUS",
        "UITI",
        "UITI_VANO",
    ]
    rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        item: dict[str, Any] = {}
        for field in fields:
            column = resolve_column(work, field)
            if column is not None:
                item[field] = _json_value(row.get(column))
        rows.append(item)
    return rows


def _weather_columns(events_df: pd.DataFrame) -> dict[str, list[str]]:
    families = {
        "precipitation": ("PREP",),
        "clouds": ("CLOUDS",),
        "visibility": ("VIS",),
        "wind_speed": ("WIND_SPD",),
        "wind_gust_speed": ("WIND_GUST_SPD",),
        "temperature": ("TEMP",),
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
        return {"available": False}
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    flat = values.stack().dropna()
    if flat.empty:
        return {"available": True, "columns": columns, "non_null_values": 0}
    stats: dict[str, Any] = {
        "available": True,
        "columns": columns,
        "non_null_values": int(flat.shape[0]),
    }
    if family == "precipitation":
        stats.update({"sum": round(float(flat.sum()), 4), "max": round(float(flat.max()), 4)})
    elif family in {"wind_speed", "wind_gust_speed"}:
        stats.update({"max": round(float(flat.max()), 4), "mean": round(float(flat.mean()), 4)})
    elif family == "temperature":
        stats.update(
            {
                "min": round(float(flat.min()), 4),
                "max": round(float(flat.max()), 4),
                "mean": round(float(flat.mean()), 4),
            }
        )
    elif family == "visibility":
        stats.update({"mean": round(float(flat.mean()), 4), "min": round(float(flat.min()), 4)})
    else:
        stats.update({"mean": round(float(flat.mean()), 4), "max": round(float(flat.max()), 4)})
    return stats


def summarize_weather_for_day(events_df: pd.DataFrame, date: str) -> dict[str, Any]:
    day = _date_filter(events_df, date)
    if day.empty:
        return {}
    detected = _weather_columns(day)
    return {family: _family_stats(day, columns, family) for family, columns in detected.items() if columns}


def summarize_variable_modes_for_day(events_df: pd.DataFrame, date: str, limit: int = 8) -> dict[str, Any]:
    day = _date_filter(events_df, date)
    if day.empty:
        return {}
    summary: dict[str, Any] = {}
    for group_name, group in VARIABLE_GROUPS.items():
        columns = [
            resolve_column(day, str(variable).replace("_i", "_0"))
            or resolve_column(day, str(variable))
            for variable in group.get("variables", [])
        ]
        columns = [column for column in columns if column is not None]
        if not columns:
            summary[group_name] = {"available": False, "columns": []}
            continue
        mode_values: dict[str, Any] = {}
        for column in columns[:limit]:
            series = day[column].dropna().astype(str)
            if series.empty:
                continue
            counts = Counter(series.tolist()).most_common(3)
            mode_values[column] = [{"value": value, "count": int(count)} for value, count in counts]
        summary[group_name] = {"available": True, "columns": columns, "modes": mode_values}
    return summary


def enrich_critical_points(events_df: pd.DataFrame, critical_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for point in critical_points:
        date = str(point["fecha_dia"])
        copy = dict(point)
        copy["attribution"] = {
            "top_causes": top_labels_for_day(events_df, date, "DESC_CAUSA")
            or top_labels_for_day(events_df, date, "COD_CAUSA"),
            "top_vanos": top_labels_for_day(events_df, date, "FID_VANO"),
            "top_protection_equipment": top_labels_for_day(events_df, date, "FID_SW")
            or top_labels_for_day(events_df, date, "COD_EQ_PROTEGE")
            or top_labels_for_day(events_df, date, "TIPO"),
            "top_circuits": top_labels_for_day(events_df, date, "CIRCUITO"),
            "top_event_rows": top_events_for_day(events_df, date),
            "variable_mode_summary": summarize_variable_modes_for_day(events_df, date),
            "weather_summary": summarize_weather_for_day(events_df, date),
        }
        enriched.append(copy)
    return enriched
