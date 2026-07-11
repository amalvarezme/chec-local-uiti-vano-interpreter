from __future__ import annotations

import importlib.util

import pandas as pd
import pytest

from chec_local_interpreter.data_loader import (
    circuit_date_range,
    filter_events,
    load_dataset,
    resolve_columns,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CIRCUITO": [101, 102],
            "FECHA": ["2026-01-01 01:00:00", "2026-01-02 02:00:00"],
            "UITI_VANO": [1.5, 2.0],
            "FID_VANO": [999, 1000],
        }
    )


def test_load_csv_preserves_ids_as_strings(tmp_path):
    path = tmp_path / "data.csv"
    _frame().to_csv(path, index=False)
    loaded = load_dataset(path)
    assert str(loaded["CIRCUITO"].dtype) == "string"
    assert str(loaded["FID_VANO"].dtype) == "string"
    assert loaded.loc[0, "CIRCUITO"] == "101"


def test_load_parquet_if_available(tmp_path):
    if importlib.util.find_spec("pyarrow") is None:
        pytest.skip("pyarrow not available")
    path = tmp_path / "data.parquet"
    _frame().to_parquet(path, index=False)
    loaded = load_dataset(path)
    assert loaded.shape[0] == 2


def test_required_column_validation_reports_missing():
    with pytest.raises(ValueError, match="Missing required columns"):
        resolve_columns(pd.DataFrame({"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"]}))


def test_filter_events_by_circuit_and_dates():
    result = filter_events(_frame(), selected_circuitos=["102"], start_date="2026-01-02", end_date="2026-01-02")
    assert result.shape[0] == 1
    assert result.iloc[0]["CIRCUITO"] == 102
    assert "fecha_dia" in result.columns


def test_circuit_date_range_multiple_events_returns_min_max():
    frame = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1"],
            "FECHA": ["2026-01-01", "2026-02-15", "2026-03-15"],
            "UITI_VANO": [1.0, 2.0, 3.0],
        }
    )
    assert circuit_date_range(frame, "C1") == ("2026-01-01", "2026-03-15")


def test_circuit_date_range_circuit_not_present_returns_none_none():
    frame = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-02"],
            "UITI_VANO": [1.0, 2.0],
        }
    )
    assert circuit_date_range(frame, "does-not-exist") == (None, None)


def test_circuit_date_range_zero_valid_date_events_returns_none_none():
    frame = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["not-a-date", ""],
            "UITI_VANO": [1.0, 2.0],
        }
    )
    assert circuit_date_range(frame, "C1") == (None, None)


def test_circuit_date_range_single_event_min_equals_max():
    frame = pd.DataFrame(
        {
            "CIRCUITO": ["C1"],
            "FECHA": ["2026-05-01"],
            "UITI_VANO": [1.0],
        }
    )
    assert circuit_date_range(frame, "C1") == ("2026-05-01", "2026-05-01")
