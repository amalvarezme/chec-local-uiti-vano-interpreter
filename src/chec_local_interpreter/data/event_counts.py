from __future__ import annotations

from collections.abc import Hashable, Sequence

import pandas as pd


def event_date_key(frame: pd.DataFrame, date_col: str = "FECHA") -> pd.Series:
    """Return parsed event-date keys; invalid dates stay unique per source row."""
    if date_col not in frame.columns:
        return pd.Series(frame.index.astype(str), index=frame.index, dtype="object")

    parsed = pd.to_datetime(frame[date_col], errors="coerce")
    keys = pd.Series(parsed.astype("object"), index=frame.index, dtype="object")
    invalid = parsed.isna()
    if invalid.any():
        keys.loc[invalid] = [f"__invalid_event_date_{idx}" for idx in frame.index[invalid]]
    return keys


def count_unique_event_dates(
    frame: pd.DataFrame,
    group_cols: str | Hashable | Sequence[str | Hashable],
    *,
    date_col: str = "FECHA",
) -> pd.Series:
    """Count events as distinct FECHA values inside each group."""
    if isinstance(group_cols, (str, bytes)) or not isinstance(group_cols, Sequence):
        group_cols = [group_cols]
    group_cols = list(group_cols)

    if frame.empty:
        return pd.Series(dtype="int64")
    if not group_cols:
        return pd.Series([event_date_key(frame, date_col=date_col).nunique()], index=["__all__"], dtype="int64")
    if any(col not in frame.columns for col in group_cols):
        missing = [str(col) for col in group_cols if col not in frame.columns]
        raise KeyError(f"Missing grouping column(s): {', '.join(missing)}")

    work = frame[group_cols].copy()
    work["_event_date_key"] = event_date_key(frame, date_col=date_col)
    return work.groupby(group_cols, dropna=False, sort=False)["_event_date_key"].nunique()
