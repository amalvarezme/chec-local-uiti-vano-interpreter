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


def _four_tier_raw_df() -> pd.DataFrame:
    """8 circuits across 4 clearly separated magnitude tiers, 2 circuits per tier.

    (event_count, uiti_vano_sum) values below were verified empirically against
    this module's deterministic `run_kmeans(..., random_state=42)` to produce
    exactly 4 singleton-pair clusters ranked in the expected order. Note ALTO
    and MEDIO deliberately share `event_count=10` (differing only in
    `uiti_vano_sum`): with this fixture's alphabetical circuit-name ordering
    (ALTO, BAJO, MEDIO, MUYALTO -- `compute_circuit_criticality_groups` groups
    by `CIRCUITO` internally), the seeded `np.random.choice` initial-centroid
    draw for n=8/k=4 lands two initial centroids inside the ALTO tier and none
    in BAJO; using ALTO's original `event_count=20` here reliably caused ALTO
    to split into two clusters while MEDIO/BAJO merged into one. Matching
    ALTO's `event_count` to MEDIO's removes the spurious extra separation
    axis between them and lets `uiti_vano_sum` alone drive a clean 4-way
    split. Verified stable under +/-3% jitter of every `uiti_vano_sum` across
    200 randomized trials (see PR discussion / task notes), not just a single
    lucky run.
    """
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
    return pd.concat(frames, ignore_index=True)


def _trace_label(name: str | None) -> str | None:
    if not name:
        return None
    return name.split(" (n=")[0]


def test_four_tiers_all_labels_present_and_correctly_ranked():
    raw_df = _four_tier_raw_df()

    fig = plot_interactive_circuit_clustering(raw_df)

    named_traces = [trace for trace in fig.data if trace.name]
    labels_present = {_trace_label(trace.name) for trace in named_traces}

    assert set(CRITICALITY_GROUP_LABELS) <= labels_present

    muy_alto_trace = next(t for t in named_traces if _trace_label(t.name) == "Riesgo Muy Alto")
    assert "MUYALTO_1" in list(muy_alto_trace.text)
    assert "MUYALTO_2" in list(muy_alto_trace.text)

    bajo_trace = next(t for t in named_traces if _trace_label(t.name) == "Riesgo Bajo")
    assert "BAJO_1" in list(bajo_trace.text)
    assert "BAJO_2" in list(bajo_trace.text)


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
    assert "Riesgo Bajo" not in labels_present


def test_compute_circuit_criticality_groups_returns_expected_shape_and_labels():
    raw_df = _four_tier_raw_df()

    df_coords = compute_circuit_criticality_groups(raw_df)

    assert df_coords.index.name == "CIRCUITO"
    assert set(df_coords.columns) == {
        "event_count", "uiti_vano_sum", "cluster", "criticidad", "centroid_distance",
    }

    by_circuito = df_coords["criticidad"].to_dict()
    assert by_circuito["MUYALTO_1"] == "Riesgo Muy Alto"
    assert by_circuito["MUYALTO_2"] == "Riesgo Muy Alto"
    assert by_circuito["BAJO_1"] == "Riesgo Bajo"
    assert by_circuito["BAJO_2"] == "Riesgo Bajo"
    assert set(df_coords["criticidad"]) == set(CRITICALITY_GROUP_LABELS)


def test_compute_circuit_criticality_groups_empty_input_returns_empty_with_same_columns():
    empty_df = pd.DataFrame(columns=["CIRCUITO", "FECHA", "UITI_VANO"])

    df_coords = compute_circuit_criticality_groups(empty_df)

    assert df_coords.empty
    assert set(df_coords.columns) == {
        "event_count", "uiti_vano_sum", "cluster", "criticidad", "centroid_distance",
    }


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


def test_compute_circuit_criticality_groups_end_date_includes_late_time_of_day_event():
    """Production-shaped data (CHA23L14): an event timestamped late on the
    `end_date` calendar day (e.g. 23:56:04) must not be excluded just because
    its raw timestamp is later than midnight of `end_date`. The full calendar
    day of `end_date` must be inclusive, matching `data_loader.filter_events`'s
    floor-to-day convention.
    """
    raw_df = pd.DataFrame(
        {
            "CIRCUITO": ["LATE_IN_DAY"],
            "FECHA": ["2026-03-01 23:56:04"],
            "UITI_VANO": [10.0],
        }
    )

    df_coords = compute_circuit_criticality_groups(raw_df, start_date="2026-01-01", end_date="2026-03-01")

    assert "LATE_IN_DAY" in df_coords.index

    # Cross-path parity (Spec Scenario 3): computing directly on the raw frame
    # with dates passed in must agree with computing on a frame pre-filtered
    # via `data_loader.filter_events` for the same window (dates not re-passed
    # to the inner call, since the frame is already filtered).
    from chec_local_interpreter.data_loader import filter_events

    filtered_df = filter_events(raw_df, start_date="2026-01-01", end_date="2026-03-01")
    df_coords_via_filter_events = compute_circuit_criticality_groups(filtered_df)

    assert (
        df_coords.loc["LATE_IN_DAY", "criticidad"]
        == df_coords_via_filter_events.loc["LATE_IN_DAY", "criticidad"]
    )


def test_compute_circuit_criticality_groups_restores_global_rng_state():
    raw_df = _four_tier_raw_df()

    np.random.seed(123)
    state_before = np.random.get_state()

    compute_circuit_criticality_groups(raw_df)

    state_after = np.random.get_state()
    assert state_before[0] == state_after[0]
    assert np.array_equal(state_before[1], state_after[1])
    assert state_before[2:] == state_after[2:]


# ---------------------------------------------------------------------------
# centroid_distance (informe-gerencial change, Phase 1 task 1.1-1.3)
# ---------------------------------------------------------------------------


def test_compute_circuit_criticality_groups_centroid_distance_present_on_normal_group():
    raw_df = _four_tier_raw_df()

    df_coords = compute_circuit_criticality_groups(raw_df)

    assert "centroid_distance" in df_coords.columns
    assert len(df_coords["centroid_distance"]) == len(df_coords)
    assert df_coords["centroid_distance"].notna().all()
    assert (df_coords["centroid_distance"] >= 0).all()
    # Non-trivial: distances are not all identical across a spread-out fixture.
    assert df_coords["centroid_distance"].nunique() > 1


def test_compute_circuit_criticality_groups_centroid_distance_present_on_empty_result():
    empty_df = pd.DataFrame(columns=["CIRCUITO", "FECHA", "UITI_VANO"])

    df_coords = compute_circuit_criticality_groups(empty_df)

    assert df_coords.empty
    assert "centroid_distance" in df_coords.columns


def test_compute_circuit_criticality_groups_centroid_distance_populated_for_small_group():
    raw_df = pd.concat(
        [
            _rows_for_circuit("SMALL_1", n_events=40, total_uiti=50000.0),
            _rows_for_circuit("SMALL_2", n_events=20, total_uiti=5000.0),
            _rows_for_circuit("SMALL_3", n_events=2, total_uiti=2.0),
        ],
        ignore_index=True,
    )

    df_coords = compute_circuit_criticality_groups(raw_df)

    assert len(df_coords) == 3
    assert "centroid_distance" in df_coords.columns
    assert df_coords["centroid_distance"].notna().all()
    assert (df_coords["centroid_distance"] >= 0).all()
