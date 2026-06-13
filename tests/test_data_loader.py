from __future__ import annotations

import importlib.util

import pandas as pd
import pytest

from chec_local_interpreter.data_loader import filter_events, load_dataset, resolve_columns


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
