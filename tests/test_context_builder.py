from __future__ import annotations

import pandas as pd

from chec_local_interpreter.attribution import enrich_critical_points
from chec_local_interpreter.context_builder import build_context_package
from chec_local_interpreter.critical_points import build_daily_series, compute_daily_features, detect_point_reasons, rank_critical_points


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
    assert context["domain_context"]["variable_groups"]
    assert "NR_T" in context["metadata"]["unavailable_optional_columns"]
    assert context["guardrails"]["do_not_detect_new_points"] is True


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
    assert context["window_summary"]["total_uiti_vano"] == 1.0
