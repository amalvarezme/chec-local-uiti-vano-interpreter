from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from chec_local_interpreter.config import CriticalityThresholds
from chec_local_interpreter.data_loader import numeric_series, resolve_column


def _date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _round_float(value: Any, digits: int = 4) -> float:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return 0.0
    return round(float(numeric), digits)


def robust_z(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if values.empty:
        return pd.Series(dtype="float64")
    median = float(values.median())
    mad = float((values - median).abs().median())
    scale = 1.4826 * mad
    if scale <= 0:
        scale = float(values.std(ddof=0))
    if scale <= 0:
        return pd.Series([0.0] * len(values), index=values.index, dtype="float64")
    return (values - median) / scale


def build_daily_series(events_df: pd.DataFrame) -> pd.DataFrame:
    if events_df.empty:
        return pd.DataFrame(
            columns=[
                "fecha_dia",
                "UITI_VANO",
                "event_count",
                "DURACION_total",
                "DURACION_available",
                "users_total",
                "users_available",
                "UITI",
            ]
        )

    work = events_df.copy()
    if "fecha_dia" not in work.columns:
        fecha_column = resolve_column(work, "FECHA")
        if fecha_column is None:
            raise ValueError("Missing required column: FECHA")
        work["fecha_dia"] = pd.to_datetime(work[fecha_column], errors="coerce").dt.floor("D")
    work = work.dropna(subset=["fecha_dia"]).copy()
    work["_UITI_VANO"] = numeric_series(work, ["UITI_VANO"])
    work["_DURACION"] = numeric_series(work, ["DURACION"])
    users_column = resolve_column(work, "TOT_USUS") or resolve_column(work, "CNT_USUS")
    work["_USERS"] = pd.to_numeric(work[users_column], errors="coerce").fillna(0.0) if users_column else 0.0
    uiti_column = resolve_column(work, "UITI")
    work["_UITI"] = pd.to_numeric(work[uiti_column], errors="coerce").fillna(0.0) if uiti_column else 0.0

    fid_column = resolve_column(work, "FID_VANO")
    fecha_col = resolve_column(work, "FECHA")
    
    work_agg = work.copy()

    daily = (
        work_agg.groupby("fecha_dia", as_index=False)
        .agg(
            UITI_VANO=("_UITI_VANO", "sum"),
            event_count=("_UITI_VANO", "size"),
            DURACION_total=("_DURACION", "sum"),
            users_total=("_USERS", "sum"),
            UITI=("_UITI", "sum"),
        )
        .sort_values("fecha_dia")
    )
    daily["DURACION_available"] = bool(resolve_column(work, "DURACION"))
    daily["users_available"] = bool(users_column)
    daily["UITI_available"] = bool(uiti_column)

    if daily.empty:
        return daily
    date_index = pd.date_range(daily["fecha_dia"].min(), daily["fecha_dia"].max(), freq="D")
    daily = (
        daily.set_index("fecha_dia")
        .reindex(date_index, fill_value=0)
        .rename_axis("fecha_dia")
        .reset_index()
    )
    for column in ("DURACION_available", "users_available", "UITI_available"):
        daily[column] = daily[column].astype(bool)
    return daily


def compute_daily_features(daily_df: pd.DataFrame, metric: str = "UITI_VANO") -> pd.DataFrame:
    frame = daily_df.copy()
    if frame.empty:
        return frame
    if "fecha_dia" not in frame.columns:
        raise ValueError("daily_df must include fecha_dia")
    frame["fecha_dia"] = pd.to_datetime(frame["fecha_dia"], errors="coerce")
    frame = frame.dropna(subset=["fecha_dia"]).sort_values("fecha_dia").copy()
    if metric not in frame.columns:
        frame[metric] = 0.0
    values = pd.to_numeric(frame[metric], errors="coerce").fillna(0.0)
    total = float(values.sum())
    frame[f"{metric}_robust_z"] = robust_z(values)
    frame[f"{metric}_delta_1d"] = values.diff().fillna(0.0)
    previous = values.shift(1)
    frame[f"{metric}_delta_pct"] = (
        frame[f"{metric}_delta_1d"] / previous.where(previous.abs() > 1e-9)
    ).replace([np.inf, -np.inf], np.nan)
    frame[f"{metric}_delta_robust_z"] = robust_z(frame[f"{metric}_delta_1d"])
    frame[f"{metric}_contribution_pct"] = values / total if total > 0 else 0.0
    frame[f"{metric}_rolling_7d_sum"] = values.rolling(7, min_periods=1).sum()
    return frame


def _reason(reason_type: str, score: float, value: Any, threshold: Any, detail: str) -> dict[str, Any]:
    return {
        "reason_type": reason_type,
        "score": round(max(float(score), 0.0), 4),
        "value": _round_float(value),
        "threshold": _round_float(threshold),
        "detail": detail,
    }


def detect_point_reasons(
    feature_df: pd.DataFrame,
    thresholds: CriticalityThresholds | None = None,
    metric: str = "UITI_VANO",
) -> dict[str, list[dict[str, Any]]]:
    thresholds = thresholds or CriticalityThresholds()
    if feature_df.empty:
        return {}

    frame = feature_df.copy()
    values = pd.to_numeric(frame.get(metric, 0.0), errors="coerce").fillna(0.0)
    if values.sum() <= 0:
        return {}

    high_value = float(values.quantile(thresholds.high_percentile))
    baseline = float(values.median())
    nonzero_days = max(int((values > 0).sum()), 1)
    dynamic_top_contributor_pct = max(
        thresholds.top_contributor_pct,
        min(0.50, 1.5 / max(nonzero_days, 1)),
    )

    reasons: dict[str, list[dict[str, Any]]] = {}
    for index, row in frame.iterrows():
        date_key = _date_text(row["fecha_dia"])
        metric_value = float(pd.to_numeric(row.get(metric), errors="coerce") or 0.0)
        robust_value = float(row.get(f"{metric}_robust_z") or 0.0)
        delta = float(row.get(f"{metric}_delta_1d") or 0.0)
        delta_z = float(row.get(f"{metric}_delta_robust_z") or 0.0)
        contribution = float(row.get(f"{metric}_contribution_pct") or 0.0)
        point_reasons = reasons.setdefault(date_key, [])

        percentile_signal = len(values) >= 3 and metric_value >= high_value > 0 and robust_value >= 1.0
        if metric_value > 0 and (robust_value >= thresholds.high_robust_z or percentile_signal):
            score = max(robust_value / max(thresholds.high_robust_z, 1.0), contribution)
            point_reasons.append(
                _reason(
                    "high_robust_z",
                    min(score, 2.0),
                    metric_value,
                    thresholds.high_robust_z,
                    "UITI_VANO esta por encima de la linea base robusta de la ventana.",
                )
            )

        if delta > 0 and (
            delta_z >= thresholds.delta_robust_z
            or (baseline > 0 and delta >= baseline and metric_value >= high_value)
            or (baseline == 0 and metric_value >= high_value and index > 0)
        ):
            point_reasons.append(
                _reason(
                    "sharp_positive_change",
                    max(delta_z / max(thresholds.delta_robust_z, 1.0), contribution),
                    delta,
                    thresholds.delta_robust_z,
                    "UITI_VANO sube bruscamente frente al dia anterior.",
                )
            )

        if contribution >= dynamic_top_contributor_pct and metric_value > 0:
            point_reasons.append(
                _reason(
                    "top_contribution_day",
                    contribution / max(dynamic_top_contributor_pct, 1e-9),
                    metric_value,
                    dynamic_top_contributor_pct,
                    "El dia aporta una fraccion alta del UITI_VANO total de la ventana.",
                )
            )

    local_peak_mask = (values.shift(1) < values) & (values.shift(-1) < values) & (values > high_value) & (values > 0)
    for index in values[local_peak_mask].index:
        date_key = _date_text(frame.loc[index, "fecha_dia"])
        reasons.setdefault(date_key, []).append(
            _reason(
                "local_peak",
                float(frame.loc[index, f"{metric}_contribution_pct"] or 0.0),
                values.loc[index],
                high_value,
                "UITI_VANO forma un pico local dentro de la serie.",
            )
        )

    return {date: items for date, items in reasons.items() if items}


def _selection_reason_text(reasons: list[dict[str, Any]]) -> str:
    details = [str(item.get("detail") or "") for item in sorted(reasons, key=lambda item: item["score"], reverse=True)]
    details = [item for item in details if item]
    return " ".join(details[:2]) if details else "Seleccionado por el detector deterministico de puntos de interes."


def rank_critical_points(
    feature_df: pd.DataFrame,
    reasons: dict[str, list[dict[str, Any]]],
    max_points: int,
    metric: str = "UITI_VANO",
) -> list[dict[str, Any]]:
    if feature_df.empty:
        return []
    frame = feature_df.copy()
    frame["fecha_text"] = frame["fecha_dia"].map(_date_text)
    indexed = frame.set_index("fecha_text", drop=False)
    points: list[dict[str, Any]] = []

    for date_key, reason_items in reasons.items():
        if date_key not in indexed.index:
            continue
        row = indexed.loc[date_key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        reason_score = sum(float(item["score"]) for item in reason_items)
        contribution = float(row.get(f"{metric}_contribution_pct") or 0.0)
        score = min(reason_score + contribution, 10.0)
        points.append(
            {
                "critical_point_id": f"cp-{date_key}",
                "fecha_dia": date_key,
                "score": round(score, 2),
                "types": sorted({str(item["reason_type"]) for item in reason_items}),
                "selection_reason": _selection_reason_text(reason_items),
                "metrics": {
                    "UITI_VANO": _round_float(row.get(metric), 1),
                    "z": _round_float(row.get(f"{metric}_robust_z"), 2),
                    "delta": _round_float(row.get(f"{metric}_delta_1d"), 1),
                    "contrib": _round_float(row.get(f"{metric}_contribution_pct"), 4),
                },
                "daily_aggregates": {
                    "events": int(row.get("event_count") or 0),
                    "dur": _round_float(row.get("DURACION_total"), 1),
                    "users": _round_float(row.get("users_total"), 0),
                },
            }
        )

    points = sorted(
        points,
        key=lambda item: (item["score"], item["metrics"]["UITI_VANO"], item["fecha_dia"]),
        reverse=True,
    )[:max_points]
    for rank, point in enumerate(points, start=1):
        point["rank"] = rank
    return points


def detect_critical_periods(
    feature_df: pd.DataFrame,
    thresholds: CriticalityThresholds | None = None,
    metric: str = "UITI_VANO",
) -> list[dict[str, Any]]:
    thresholds = thresholds or CriticalityThresholds()
    if feature_df.empty:
        return []
    values = pd.to_numeric(feature_df.get(metric, 0.0), errors="coerce").fillna(0.0)
    if values.sum() <= 0:
        return []
    cutoff = float(values.quantile(thresholds.sustained_percentile))
    active = (values >= cutoff) & (values > 0)
    periods: list[dict[str, Any]] = []
    start_index: int | None = None
    active_list = active.tolist() + [False]
    for index, is_active in enumerate(active_list):
        if is_active and start_index is None:
            start_index = index
        if not is_active and start_index is not None:
            end_index = index - 1
            days = end_index - start_index + 1
            if days >= thresholds.sustained_min_days:
                period_values = values.iloc[start_index : end_index + 1]
                start_date = _date_text(feature_df.iloc[start_index]["fecha_dia"])
                end_date = _date_text(feature_df.iloc[end_index]["fecha_dia"])
                periods.append(
                    {
                        "critical_period_id": f"period-{start_date}-{end_date}",
                        "start_date": start_date,
                        "end_date": end_date,
                        "days": int(days),
                        "period_type": "sustained_elevated_uiti_vano",
                        "score": _round_float(period_values.sum() / max(values.sum(), 1e-9)),
                        "total_uiti_vano": _round_float(period_values.sum()),
                        "summary": f"UITI_VANO permanecio elevado durante {days} dias entre {start_date} y {end_date}.",
                    }
                )
            start_index = None
    return sorted(periods, key=lambda item: item["score"], reverse=True)
