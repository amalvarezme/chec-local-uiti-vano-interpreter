from __future__ import annotations

import pandas as pd
import pytest

from chec_local_interpreter.attribution import enrich_critical_points
from chec_local_interpreter.context_builder import _compute_circuit_characterization, build_context_package, vano_series_records, window_series_records
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


# --- La serie del historiador va por VENTANAS, no por dias -------------------------------


def test_window_series_covers_every_window_including_the_empty_ones():
    """La ventana es la unidad de analisis de los cuadernos 04, 05 y 06 -- una bolsa
    es (vano, ventana) --, y el historiador recibia una serie DIARIA. Peor: recortada
    a 60 dias y filtrando los dias en cero, asi que describia los picos y no la serie.

    Una ventana sin eventos es un dato, no un hueco: leer "hubo cinco ventanas
    tranquilas seguidas" es distinto de no ver esas ventanas. El cuaderno 06 ya dibuja
    su serie asi.
    """
    eventos = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1"],
            "FID_VANO": ["V1", "V1", "V2"],
            "FECHA": ["2026-01-05", "2026-03-20", "2026-03-21"],
            "UITI_VANO": [2.0, 5.0, 1.0],
        }
    )

    serie = window_series_records(eventos, circuito="C1")

    etiquetas = [r["w"] for r in serie]
    assert len(etiquetas) == len(set(etiquetas)), "una ventana no puede repetirse"
    # Enero y marzo tienen eventos; las ventanas intermedias van en cero y SIGUEN ahi.
    assert any(r["uv"] == 0.0 and r["n"] == 0 for r in serie), (
        "las ventanas sin eventos tienen que aparecer, en cero"
    )
    con_eventos = [r for r in serie if r["n"] > 0]
    assert con_eventos, "las ventanas con eventos no pueden perderse"
    assert sum(r["uv"] for r in serie) == pytest.approx(8.0)
    assert sum(r["n"] for r in serie) == 3


def test_window_series_is_empty_for_a_circuit_with_no_events():
    eventos = pd.DataFrame(
        {"CIRCUITO": ["C2"], "FID_VANO": ["V9"], "FECHA": ["2026-01-05"],
         "UITI_VANO": [1.0]}
    )

    assert window_series_records(eventos, circuito="C1") == []


def test_context_package_carries_the_window_series():
    eventos = pd.DataFrame(
        {"CIRCUITO": ["C1", "C1"], "FID_VANO": ["V1", "V1"],
         "FECHA": ["2026-01-05", "2026-02-20"], "UITI_VANO": [2.0, 5.0]}
    )
    daily = build_daily_series(eventos)

    paquete = build_context_package(
        events_df=eventos, daily_df=daily, critical_points=[], critical_periods=[],
        selected_circuitos=["C1"], start_date="2026-01-01", end_date="2026-03-01",
    )

    assert paquete["ventanas"], "el paquete del historiador tiene que traer las ventanas"
    assert {"w", "uv", "n"} <= set(paquete["ventanas"][0])


def test_vano_series_covers_every_window_for_each_identified_vano():
    """La serie de los vanos que el diagnostico señalo, para verlos en el tiempo y no
    solo en la ventana en que salieron criticos. Completa, con cero donde el vano no
    registro eventos: una ventana tranquila de un vano critico es informacion -- dice
    que el problema es reciente o intermitente, no cronico."""
    eventos = pd.DataFrame({
        "CIRCUITO": ["C1", "C1", "C1"],
        "FID_VANO": ["V1", "V1", "V2"],
        "FECHA": ["2026-01-05", "2026-03-20", "2026-01-06"],
        "UITI_VANO": [2.0, 5.0, 1.0],
    })

    series = vano_series_records(eventos, circuito="C1", fids=["V1", "V2"])

    assert [s["fid"] for s in series] == ["V1", "V2"], "en el orden pedido"
    for s in series:
        assert len(s["uv"]) == len(s["w"]) == len(s["n"])
        assert any(u == 0.0 for u in s["uv"]), "las ventanas sin eventos van en cero"
    assert sum(series[0]["uv"]) == pytest.approx(7.0)


def test_vano_series_without_fids_is_empty():
    eventos = pd.DataFrame({"CIRCUITO": ["C1"], "FID_VANO": ["V1"],
                            "FECHA": ["2026-01-05"], "UITI_VANO": [1.0]})

    assert vano_series_records(eventos, circuito="C1", fids=[]) == []
