from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from chec_local_interpreter.config import ID_COLUMNS, REQUIRED_COLUMNS
from chec_local_interpreter.schema import ColumnResolution, OPTIONAL_COLUMNS


def column_lookup(frame: pd.DataFrame) -> dict[str, str]:
    return {str(column).strip().upper(): str(column) for column in frame.columns}


def resolve_column(frame: pd.DataFrame, name: str) -> str | None:
    return column_lookup(frame).get(name.upper())


def resolve_columns(frame: pd.DataFrame) -> ColumnResolution:
    lookup = column_lookup(frame)
    required = {name: lookup[name] for name in REQUIRED_COLUMNS if name in lookup}
    missing = [name for name in REQUIRED_COLUMNS if name not in lookup]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    optional = {name: lookup[name] for name in OPTIONAL_COLUMNS if name in lookup}
    unavailable = [name for name in OPTIONAL_COLUMNS if name not in lookup]
    return ColumnResolution(required=required, optional=optional, unavailable_optional=unavailable)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, low_memory=False)


def load_dataset(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Dataset not found: {source}")
    suffix = source.suffix.lower()
    if suffix == ".csv":
        frame = _read_csv(source)
    elif suffix == ".parquet":
        frame = pd.read_parquet(source)
    elif suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(source, dtype=str)
    else:
        raise ValueError(f"Unsupported dataset format: {suffix}")

    validate_required_columns(frame)
    return normalize_id_columns(frame)


def validate_required_columns(frame: pd.DataFrame) -> None:
    resolve_columns(frame)


def normalize_id_columns(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    lookup = column_lookup(work)
    for expected in ID_COLUMNS:
        column = lookup.get(expected)
        if column is not None:
            work[column] = work[column].astype("string")
    return work


def parse_fecha(frame: pd.DataFrame) -> pd.Series:
    column = resolve_column(frame, "FECHA")
    if column is None:
        raise ValueError("Missing required column: FECHA")
    return pd.to_datetime(frame[column], errors="coerce")


def numeric_series(frame: pd.DataFrame, candidates: Iterable[str], default: float = 0.0) -> pd.Series:
    for candidate in candidates:
        column = resolve_column(frame, candidate)
        if column is not None:
            return pd.to_numeric(frame[column], errors="coerce").fillna(default)
    return pd.Series([default] * len(frame), index=frame.index, dtype="float64")


def text_series(frame: pd.DataFrame, candidates: Iterable[str], default: str = "") -> pd.Series:
    for candidate in candidates:
        column = resolve_column(frame, candidate)
        if column is not None:
            return frame[column].fillna(default).astype(str)
    return pd.Series([default] * len(frame), index=frame.index, dtype="object")


def filter_events(
    frame: pd.DataFrame,
    *,
    selected_circuitos: Iterable[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    validate_required_columns(frame)
    work = frame.copy()
    circuito_column = resolve_column(work, "CIRCUITO")
    fecha = parse_fecha(work)
    work["fecha_dia"] = fecha.dt.floor("D")
    work = work.dropna(subset=["fecha_dia"]).copy()

    circuits = [str(value) for value in selected_circuitos or [] if str(value).strip()]
    if circuits and circuito_column is not None:
        work = work[work[circuito_column].astype(str).isin(circuits)].copy()

    if start_date:
        work = work[work["fecha_dia"] >= pd.to_datetime(start_date).floor("D")].copy()
    if end_date:
        work = work[work["fecha_dia"] <= pd.to_datetime(end_date).floor("D")].copy()
    return work


def available_circuits(frame: pd.DataFrame) -> list[str]:
    column = resolve_column(frame, "CIRCUITO")
    if column is None:
        return []
    return sorted(frame[column].dropna().astype(str).unique().tolist())


def dataset_summary(frame: pd.DataFrame) -> dict[str, object]:
    fecha = parse_fecha(frame)
    return {
        "shape": [int(frame.shape[0]), int(frame.shape[1])],
        "date_min": None if fecha.dropna().empty else fecha.min().date().isoformat(),
        "date_max": None if fecha.dropna().empty else fecha.max().date().isoformat(),
        "available_circuits_count": len(available_circuits(frame)),
    }
