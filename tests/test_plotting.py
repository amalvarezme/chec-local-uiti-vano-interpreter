from __future__ import annotations

import numpy as np
import pandas as pd

from chec_local_interpreter.plotting import (
    CRITICALITY_GROUP_LABELS,
    compute_circuit_criticality_groups,
    plot_interactive_circuit_clustering,
)


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


def _five_tier_raw_df() -> pd.DataFrame:
    """10 circuits across 5 clearly separated magnitude tiers, 2 circuits per tier.

    (event_count, uiti_vano_sum) values below were verified empirically against
    this module's deterministic `run_kmeans(..., random_state=42)` to produce
    exactly 5 singleton-pair clusters ranked in the expected order -- with only
    6 points the tied-lowest pair can occasionally land on two *different*
    initial K-Means centroids (since they are the closest pair yet each is
    already its own cluster once chosen as a seed) and never merge, so 2 points
    per tier is used for a clustering result that is robust, not just close.
    """
    frames = [
        _rows_for_circuit("MUYALTA_1", n_events=40, total_uiti=50000.0),
        _rows_for_circuit("MUYALTA_2", n_events=40, total_uiti=55000.0),
        _rows_for_circuit("ALTA_1", n_events=20, total_uiti=5000.0),
        _rows_for_circuit("ALTA_2", n_events=20, total_uiti=5500.0),
        _rows_for_circuit("MEDIA_1", n_events=10, total_uiti=500.0),
        _rows_for_circuit("MEDIA_2", n_events=10, total_uiti=550.0),
        _rows_for_circuit("BAJA_1", n_events=4, total_uiti=40.0),
        _rows_for_circuit("BAJA_2", n_events=4, total_uiti=45.0),
        _rows_for_circuit("MUYBAJA_1", n_events=2, total_uiti=2.0),
        _rows_for_circuit("MUYBAJA_2", n_events=2, total_uiti=4.0),
    ]
    return pd.concat(frames, ignore_index=True)


def _trace_label(name: str | None) -> str | None:
    if not name:
        return None
    return name.split(" (n=")[0]


def test_five_tiers_all_labels_present_and_correctly_ranked():
    raw_df = _five_tier_raw_df()

    fig = plot_interactive_circuit_clustering(raw_df)

    named_traces = [trace for trace in fig.data if trace.name]
    labels_present = {_trace_label(trace.name) for trace in named_traces}

    assert set(CRITICALITY_GROUP_LABELS) <= labels_present

    muy_alta_trace = next(t for t in named_traces if _trace_label(t.name) == "Muy Alta")
    assert "MUYALTA_1" in list(muy_alta_trace.text)
    assert "MUYALTA_2" in list(muy_alta_trace.text)

    muy_baja_trace = next(t for t in named_traces if _trace_label(t.name) == "Muy Baja")
    assert "MUYBAJA_1" in list(muy_baja_trace.text)
    assert "MUYBAJA_2" in list(muy_baja_trace.text)


def test_two_circuits_degrade_gracefully_without_crash():
    raw_df = pd.concat(
        [
            _rows_for_circuit("D1", n_events=2, total_uiti=2.0),
            _rows_for_circuit("D2", n_events=20, total_uiti=50000.0),
        ],
        ignore_index=True,
    )

    fig = plot_interactive_circuit_clustering(raw_df)

    named_traces = [trace for trace in fig.data if trace.name]
    labels_present = {_trace_label(trace.name) for trace in named_traces}

    assert len(labels_present) <= 2
    assert "Muy Baja" not in labels_present


def test_compute_circuit_criticality_groups_returns_expected_shape_and_labels():
    raw_df = _five_tier_raw_df()

    df_coords = compute_circuit_criticality_groups(raw_df)

    assert df_coords.index.name == "CIRCUITO"
    assert set(df_coords.columns) == {"event_count", "uiti_vano_sum", "cluster", "criticidad"}

    by_circuito = df_coords["criticidad"].to_dict()
    assert by_circuito["MUYALTA_1"] == "Muy Alta"
    assert by_circuito["MUYALTA_2"] == "Muy Alta"
    assert by_circuito["MUYBAJA_1"] == "Muy Baja"
    assert by_circuito["MUYBAJA_2"] == "Muy Baja"
    assert set(df_coords["criticidad"]) == set(CRITICALITY_GROUP_LABELS)


def test_compute_circuit_criticality_groups_empty_input_returns_empty_with_same_columns():
    empty_df = pd.DataFrame(columns=["CIRCUITO", "FECHA", "UITI_VANO"])

    df_coords = compute_circuit_criticality_groups(empty_df)

    assert df_coords.empty
    assert set(df_coords.columns) == {"event_count", "uiti_vano_sum", "cluster", "criticidad"}


def test_compute_circuit_criticality_groups_date_filter_excludes_out_of_window_rows():
    raw_df = pd.concat(
        [
            _rows_for_circuit("IN_WINDOW", n_events=5, total_uiti=100.0, start="2026-02-01"),
            _rows_for_circuit("OUT_OF_WINDOW", n_events=5, total_uiti=100.0, start="2020-01-01"),
        ],
        ignore_index=True,
    )

    df_coords = compute_circuit_criticality_groups(raw_df, start_date="2026-01-01", end_date="2026-03-01")

    assert "IN_WINDOW" in df_coords.index
    assert "OUT_OF_WINDOW" not in df_coords.index


def test_compute_circuit_criticality_groups_restores_global_rng_state():
    raw_df = _five_tier_raw_df()

    np.random.seed(123)
    state_before = np.random.get_state()

    compute_circuit_criticality_groups(raw_df)

    state_after = np.random.get_state()
    assert state_before[0] == state_after[0]
    assert np.array_equal(state_before[1], state_after[1])
    assert state_before[2:] == state_after[2:]
