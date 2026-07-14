from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from chec_impacto.data.climate import (
    combine_payloads,
    hour_floor,
    parse_local_bogota_to_utc,
    save_completed_dataset,
    slice_time_window,
    to_utc_iso,
)


def test_parse_local_bogota_to_utc_converts_timezone():
    result = parse_local_bogota_to_utc(pd.Series(["2026-01-01 00:00:00", "bad"]), fecha_format="%Y-%m-%d %H:%M:%S")

    assert result.iloc[0].isoformat() == "2026-01-01T05:00:00+00:00"
    assert pd.isna(result.iloc[1])


def test_to_utc_iso_and_hour_floor():
    dt = datetime(2026, 1, 1, 5, 45, 30, tzinfo=timezone.utc)

    assert to_utc_iso(dt) == "2026-01-01T05:45:30Z"
    assert hour_floor(dt) == datetime(2026, 1, 1, 5, tzinfo=timezone.utc)


def test_slice_time_window_filters_matching_length_values():
    times = pd.date_range("2026-01-01T00:00:00Z", periods=4, freq="h")
    payload = {"time": times, "temp": np.array([1.0, 2.0, 3.0, 4.0]), "meta": ["keep"]}

    result = slice_time_window(payload, times[1].to_pydatetime(), times[2].to_pydatetime())

    assert list(result["time"]) == list(times[1:3])
    assert result["temp"].tolist() == [2.0, 3.0]
    assert result["meta"] == ["keep"]


def test_combine_payloads_merges_times_and_prefers_later_payload_values():
    times_a = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="h")
    times_b = pd.date_range("2026-01-01T01:00:00Z", periods=2, freq="h")

    result = combine_payloads([
        {"time": times_a, "temp": np.array([10.0, 11.0])},
        {"time": times_b, "temp": np.array([21.0, 22.0])},
    ])

    assert [ts.isoformat() for ts in result["time"]] == [
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T01:00:00+00:00",
        "2026-01-01T02:00:00+00:00",
    ]
    assert result["temp"].tolist() == [10.0, 21.0, 22.0]


def test_save_completed_dataset_drops_transient_event_time_column(tmp_path):
    output = tmp_path / "completed.csv"
    df = pd.DataFrame({"FECHA": ["2026-01-01"], "event_time_iso_utc": ["drop"]})

    save_completed_dataset(df, output)

    saved = pd.read_csv(output)
    assert saved.columns.tolist() == ["FECHA"]
