from __future__ import annotations

import pandas as pd

from chec_local_interpreter.attribution import enrich_critical_points
from chec_local_interpreter.context_builder import _compute_circuit_characterization, build_context_package
from chec_local_interpreter.critical_points import build_daily_series, compute_daily_features, detect_point_reasons, rank_critical_points
from chec_local_interpreter.plotting import CRITICALITY_GROUP_LABELS


def test_context_package_includes_core_sections_and_missing_optional_columns():
    events = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-02"],
            "UITI_VANO": [1.0, 10.0],
            "DESC_CAUSA": ["Vegetacion", "Vegetacion"],
        }
    )
    daily = build_daily_series(events)
    features = compute_daily_features(daily)
    points = enrich_critical_points(events, rank_critical_points(features, detect_point_reasons(features), 12))
    context = build_context_package(
        events_df=events,
        daily_df=daily,
        critical_points=points,
        critical_periods=[],
        selected_circuitos=["C1"],
        start_date="2026-01-01",
        end_date="2026-01-02",
    )
    assert context["selected_context"]["circuitos"] == ["C1"]
    assert context["selected_context"]["indicator"] == "UITI_VANO"
    assert context["critical_points"]
    assert context["domain"]["variable_groups"]
    assert "NR_T" in context["metadata"]["unavailable_cols"]


def test_missing_optional_columns_do_not_crash_context_generation():
    events = pd.DataFrame({"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"], "UITI_VANO": [1]})
    daily = build_daily_series(events)
    context = build_context_package(
        events_df=events,
        daily_df=daily,
        critical_points=[],
        critical_periods=[],
        selected_circuitos=["C1"],
        start_date="2026-01-01",
        end_date="2026-01-01",
    )
    assert context["summary"]["total_uv"] == 1.0


def _rows_for_circuit(circuit: str, n_events: int, total_uiti: float, start: str = "2026-01-01") -> pd.DataFrame:
    """Build `n_events` distinct-date rows for `circuit` whose UITI_VANO sums to `total_uiti`."""
    dates = pd.date_range(start, periods=n_events, freq="D").strftime("%Y-%m-%d").tolist()
    per_event = total_uiti / n_events
    return pd.DataFrame(
        {
            "CIRCUITO": [circuit] * n_events,
            "FECHA": dates,
            "UITI_VANO": [per_event] * n_events,
        }
    )


def test_compute_circuit_characterization_uses_four_criticality_tiers():
    # 8 circuits across 4 clearly separated magnitude tiers, 2 per tier. Values
    # verified empirically against the deterministic K-Means (random_state=42)
    # used by both plotting.py and context_builder.py to produce exactly 4
    # singleton-pair clusters ranked in the expected order (same fixture as
    # `tests/test_plotting.py::_four_tier_raw_df`).
    frames = [
        _rows_for_circuit("MUYALTO_1", n_events=40, total_uiti=50000.0),
        _rows_for_circuit("MUYALTO_2", n_events=40, total_uiti=55000.0),
        _rows_for_circuit("ALTO_1", n_events=10, total_uiti=5000.0),
        _rows_for_circuit("ALTO_2", n_events=10, total_uiti=5500.0),
        _rows_for_circuit("MEDIO_1", n_events=10, total_uiti=500.0),
        _rows_for_circuit("MEDIO_2", n_events=10, total_uiti=550.0),
        _rows_for_circuit("BAJO_1", n_events=4, total_uiti=40.0),
        _rows_for_circuit("BAJO_2", n_events=4, total_uiti=45.0),
    ]
    df = pd.concat(frames, ignore_index=True)

    # Select 4 circuits (cap in _compute_circuit_characterization), keeping both extremes.
    selected_circuitos = ["BAJO_1", "MEDIO_1", "ALTO_1", "MUYALTO_1"]
    results = _compute_circuit_characterization(df, selected_circuitos=selected_circuitos)

    assert results
    for row in results:
        assert row["criticidad"] in CRITICALITY_GROUP_LABELS

    by_circuito = {row["circuito"]: row for row in results}
    assert by_circuito["MUYALTO_1"]["criticidad"] == "Riesgo Muy Alto"
    if "BAJO_1" in by_circuito:
        assert by_circuito["BAJO_1"]["criticidad"] == "Riesgo Bajo"


def test_compute_circuit_characterization_matches_shared_clustering_helper():
    """Both call sites must derive `criticidad` from the same shared helper."""
    from chec_local_interpreter.plotting import compute_circuit_criticality_groups

    frames = [
        _rows_for_circuit("MUYALTO_1", n_events=40, total_uiti=50000.0),
        _rows_for_circuit("MUYALTO_2", n_events=40, total_uiti=55000.0),
        _rows_for_circuit("ALTO_1", n_events=10, total_uiti=5000.0),
        _rows_for_circuit("ALTO_2", n_events=10, total_uiti=5500.0),
        _rows_for_circuit("MEDIO_1", n_events=10, total_uiti=500.0),
        _rows_for_circuit("MEDIO_2", n_events=10, total_uiti=550.0),
        _rows_for_circuit("BAJO_1", n_events=4, total_uiti=40.0),
        _rows_for_circuit("BAJO_2", n_events=4, total_uiti=45.0),
    ]
    df = pd.concat(frames, ignore_index=True)
    selected_circuitos = ["BAJO_1", "MEDIO_1", "ALTO_1", "MUYALTO_1"]

    results = _compute_circuit_characterization(df, selected_circuitos=selected_circuitos)
    expected = compute_circuit_criticality_groups(df)

    for row in results:
        assert row["criticidad"] == expected.loc[row["circuito"], "criticidad"]
