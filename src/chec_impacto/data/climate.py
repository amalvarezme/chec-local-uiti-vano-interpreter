"""Climate completion helpers for Open-Meteo notebook workflows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

BOGOTA_TZ = ZoneInfo("America/Bogota")


def parse_local_bogota_to_utc(series_str: pd.Series, *, fecha_format: str | None = None) -> pd.Series:
    """Parse local Bogota timestamps and convert them to UTC."""
    dt_local = pd.to_datetime(series_str, errors="coerce", format=fecha_format)
    dt_local = dt_local.dt.tz_localize(BOGOTA_TZ, nonexistent="NaT", ambiguous="NaT")
    return dt_local.dt.tz_convert(timezone.utc)


def to_utc_iso(dt: datetime) -> str:
    """Format a datetime as UTC ISO-8601 with Z suffix."""
    return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def hour_floor(dt: datetime) -> datetime:
    """Floor a datetime to the UTC hour."""
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def call_openmeteo(openmeteo_client, url: str, params: dict, var_order: list[str], *, forecast_url: str) -> dict:
    """Call Open-Meteo and return a payload with UTC hourly timestamps."""
    request_params = {
        "latitude": params["latitude"],
        "longitude": params["longitude"],
        "timezone": "UTC",
        "hourly": var_order,
    }
    if url == forecast_url:
        if "past_days" in params:
            request_params["past_days"] = params["past_days"]
    else:
        request_params["start_date"] = params["start_date"]
        request_params["end_date"] = params["end_date"]

    responses = openmeteo_client.weather_api(url, params=request_params)
    hourly = responses[0].Hourly()
    times = pd.date_range(
        start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
        end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=hourly.Interval()),
        inclusive="left",
    )

    output = {"time": times}
    for i, var_name in enumerate(var_order):
        output[var_name] = hourly.Variables(i).ValuesAsNumpy()
    return output


def slice_time_window(payload: dict, start_dt: datetime, end_dt: datetime) -> dict:
    """Slice a payload to an inclusive UTC time window."""
    times = pd.to_datetime(payload["time"], utc=True)
    start = pd.Timestamp(start_dt).tz_convert("UTC") if pd.Timestamp(start_dt).tzinfo else pd.Timestamp(start_dt, tz="UTC")
    end = pd.Timestamp(end_dt).tz_convert("UTC") if pd.Timestamp(end_dt).tzinfo else pd.Timestamp(end_dt, tz="UTC")
    mask = (times >= start) & (times <= end)

    sliced = {"time": times[mask]}
    for key, value in payload.items():
        if key == "time":
            continue
        if len(value) == len(times):
            sliced[key] = value[mask]
        else:
            sliced[key] = value
    return sliced


def combine_payloads(payloads: list[dict]) -> dict:
    """Combine Open-Meteo payloads by timestamp, preferring later payload values."""
    all_times = pd.Index([], dtype="datetime64[ns, UTC]")
    for payload in payloads:
        all_times = all_times.union(pd.Index(pd.to_datetime(payload["time"], utc=True)))
    all_times = all_times.sort_values()

    output = {"time": all_times}
    keys = set().union(*(set(payload.keys()) for payload in payloads)) - {"time"}
    for key in keys:
        series = pd.Series(index=all_times, dtype=float)
        for payload in payloads:
            if key in payload:
                src_idx = pd.Index(pd.to_datetime(payload["time"], utc=True))
                series.update(pd.Series(payload[key], index=src_idx))
        output[key] = series.reindex(all_times).to_numpy()
    return output


def get_hourly_window(
    openmeteo_client,
    lat: float,
    lon: float,
    start_dt_utc: datetime,
    end_dt_utc: datetime,
    *,
    archive_url: str,
    forecast_url: str,
    archive_vars: list[str],
    forecast_vars: list[str],
    now_utc: datetime | None = None,
) -> dict:
    """Fetch and slice an hourly Open-Meteo window across archive/forecast boundaries."""
    now_utc = now_utc or datetime.now(timezone.utc)
    boundary = now_utc - timedelta(days=5)
    payloads = []
    if end_dt_utc <= boundary:
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_dt_utc.date().isoformat(),
            "end_date": end_dt_utc.date().isoformat(),
        }
        payloads.append(call_openmeteo(openmeteo_client, archive_url, params, archive_vars, forecast_url=forecast_url))
    elif start_dt_utc >= boundary:
        diff_days = (now_utc - start_dt_utc).days + 1
        params = {"latitude": lat, "longitude": lon, "past_days": min(7, max(1, diff_days))}
        payloads.append(call_openmeteo(openmeteo_client, forecast_url, params, forecast_vars, forecast_url=forecast_url))
    else:
        params_archive = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_dt_utc.date().isoformat(),
            "end_date": boundary.date().isoformat(),
        }
        payloads.append(call_openmeteo(openmeteo_client, archive_url, params_archive, archive_vars, forecast_url=forecast_url))
        diff_days = (now_utc - boundary).days + 1
        params_forecast = {"latitude": lat, "longitude": lon, "past_days": min(7, max(1, diff_days))}
        payloads.append(call_openmeteo(openmeteo_client, forecast_url, params_forecast, forecast_vars, forecast_url=forecast_url))
    return slice_time_window(combine_payloads(payloads), start_dt_utc, end_dt_utc)


def save_completed_dataset(df: pd.DataFrame, output_path: str | Path) -> None:
    """Save a completed climate dataset without transient helper columns."""
    columns_to_drop = [column for column in ["event_time_iso_utc"] if column in df.columns]
    df.drop(columns=columns_to_drop).to_csv(output_path, index=False)
