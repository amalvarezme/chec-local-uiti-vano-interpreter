from __future__ import annotations

import pandas as pd

from chec_local_interpreter.plotting import (
    CRITICALITY_GROUP_LABELS,
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
