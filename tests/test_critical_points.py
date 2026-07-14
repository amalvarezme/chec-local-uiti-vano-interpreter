from __future__ import annotations

import pandas as pd

from chec_local_interpreter.config import CriticalityThresholds
from chec_local_interpreter.analysis.critical_points import (
    build_daily_series,
    compute_daily_features,
    detect_critical_periods,
    detect_point_reasons,
    rank_critical_points,
    robust_z,
)


def test_robust_z_constant_series_returns_zeroes():
    result = robust_z(pd.Series([5, 5, 5]))
    assert result.tolist() == [0.0, 0.0, 0.0]


def test_high_spike_day_is_detected():
    daily = pd.DataFrame(
        {
            "fecha_dia": pd.date_range("2026-01-01", periods=7),
            "UITI_VANO": [1, 1, 2, 100, 2, 1, 1],
            "event_count": [1] * 7,
        }
    )
    features = compute_daily_features(daily)
    reasons = detect_point_reasons(features)
    points = rank_critical_points(features, reasons, max_points=12)
    assert points[0]["fecha_dia"] == "2026-01-04"
    assert "local_peak" in points[0]["types"]


def test_sharp_increase_day_is_detected():
    daily = pd.DataFrame(
        {
            "fecha_dia": pd.date_range("2026-02-01", periods=5),
            "UITI_VANO": [0, 0, 0, 50, 0],
            "event_count": [0, 0, 0, 1, 0],
        }
    )
    features = compute_daily_features(daily)
    reasons = detect_point_reasons(features)
    points = rank_critical_points(features, reasons, max_points=12)
    assert points[0]["fecha_dia"] == "2026-02-04"
    assert "sharp_positive_change" in points[0]["types"]


def test_detect_critical_periods_with_custom_min_days():
    daily = pd.DataFrame(
        {
            "fecha_dia": pd.date_range("2026-03-01", periods=7),
            "UITI_VANO": [1, 10, 11, 12, 13, 14, 1],
        }
    )
    features = compute_daily_features(daily)
    periods = detect_critical_periods(features, CriticalityThresholds(sustained_min_days=2))
    assert periods
    assert periods[0]["period_type"] == "sustained_elevated_uiti_vano"


def test_build_daily_series_fills_missing_dates_without_quality_error():
    events = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-03"],
            "UITI_VANO": [2, 3],
        }
    )
    daily = build_daily_series(events)
    assert daily.shape[0] == 3
    assert daily.loc[1, "UITI_VANO"] == 0


def test_build_daily_series_counts_unique_fecha_values_as_events():
    events = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1"],
            "FECHA": ["2026-01-01 08:00", "2026-01-01 08:00", "2026-01-01 09:00"],
            "UITI_VANO": [2, 3, 4],
        }
    )
    daily = build_daily_series(events)
    assert daily.loc[0, "event_count"] == 2
