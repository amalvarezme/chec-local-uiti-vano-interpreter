from __future__ import annotations

import importlib.util

import pandas as pd
import pytest

from chec_local_interpreter.data_loader import (
    circuit_date_range,
    columnas_declaradas,
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


# --- Leer solo las columnas que el flujo declara ------------------------------------------


def test_loading_only_the_declared_columns_skips_the_rest(tmp_path):
    """El CSV real trae 273 columnas -- casi todas rezagos climaticos -- y leerlas todas
    como texto cuesta 3.688 MB de pico, MEDIDO. El flujo del informe declara cuales usa:
    las requeridas, las opcionales y los identificadores. Los rezagos solo los necesita el
    constructor del catalogo, que lee el CSV por su cuenta y esta cacheado.
    """
    import pandas as pd

    csv = tmp_path / "datos.csv"
    pd.DataFrame({
        "CIRCUITO": ["C1"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1.0"],
        "FID_VANO": ["V1"], "DURACION": ["5"],
        "prep_lag_0": ["0.1"], "temp_lag_3": ["20.0"],
    }).to_csv(csv, index=False)

    frame = load_dataset(csv, columns=columnas_declaradas())

    assert {"CIRCUITO", "FECHA", "UITI_VANO", "FID_VANO", "DURACION"} <= set(frame.columns)
    assert "prep_lag_0" not in frame.columns
    assert "temp_lag_3" not in frame.columns


def test_declared_columns_absent_from_the_file_are_simply_not_read(tmp_path):
    """`usecols` revienta si se pide una columna que el archivo no trae, y una opcional
    ausente es un caso NORMAL -- es lo que `unavailable_optional` existe para reportar."""
    import pandas as pd

    csv = tmp_path / "datos.csv"
    pd.DataFrame({"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"],
                  "UITI_VANO": ["1.0"]}).to_csv(csv, index=False)

    frame = load_dataset(csv, columns=columnas_declaradas())

    assert list(frame.columns) == ["CIRCUITO", "FECHA", "UITI_VANO"]


def test_the_declared_set_keeps_the_unavailable_optional_report_honest(tmp_path):
    """Si la lectura recortada dejara fuera una opcional que el archivo SI trae, el
    contexto la reportaria como no disponible y el guardrail prohibiria citarla: el
    informe perderia una variable real sin que nada lo dijera."""
    import pandas as pd
    from chec_local_interpreter.schema import OPTIONAL_COLUMNS

    csv = tmp_path / "datos.csv"
    columnas = {"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1.0"]}
    for opcional in OPTIONAL_COLUMNS:
        columnas.setdefault(opcional, ["x"])
    pd.DataFrame(columnas).to_csv(csv, index=False)

    frame = load_dataset(csv, columns=columnas_declaradas())

    assert resolve_columns(frame).unavailable_optional == []


def test_loading_without_a_column_list_is_unchanged(tmp_path):
    """Los otros consumidores del cargador no cambian de comportamiento."""
    import pandas as pd

    csv = tmp_path / "datos.csv"
    pd.DataFrame({"CIRCUITO": ["C1"], "FECHA": ["2026-01-01"], "UITI_VANO": ["1.0"],
                  "prep_lag_0": ["0.1"]}).to_csv(csv, index=False)

    assert "prep_lag_0" in load_dataset(csv).columns
