"""Helpers for MGCECDL document replication notebooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd


def json_default(value):
    """Convert common pandas/numpy scalar values to JSON-compatible values."""
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def scalar_python(value):
    """Normalize common scalar values for stable dictionaries and CSV serialization."""
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def serialize_dict_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert dictionary-valued columns to JSON strings for stable CSV output."""
    out = df.copy()
    for col in out.columns:
        if out[col].map(lambda value: isinstance(value, dict)).any():
            out[col] = out[col].map(
                lambda value: json.dumps(value, ensure_ascii=False, default=json_default)
                if isinstance(value, dict)
                else value
            )
    return out


def save_result(df: pd.DataFrame, output_path: str | Path, name: str) -> None:
    """Save a document section as UTF-8 BOM CSV for Excel compatibility."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialize_dict_columns(df).to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Guardado {name}: {output_path} | filas={len(df):,} | columnas={df.shape[1]:,}")


def build_top_vars_with_values(row, *, top_col: str = "_TOP_VARS", top_k: int = 20) -> dict:
    """Attach original row values to the top MGCECDL relevance variables."""
    output = {}
    top_vars = row.get(top_col, {})
    if not isinstance(top_vars, dict):
        return output
    for variable, relevance in list(top_vars.items())[:top_k]:
        output[variable] = {
            "valor_original": scalar_python(row[variable]) if variable in row.index else None,
            "relevancia_mgcecdl": float(relevance),
        }
    return output


def aggregate_weighted_borda(
    df: pd.DataFrame,
    group_cols: Sequence[str],
    *,
    top_col: str = "_TOP_VARS",
    top_k: int = 20,
) -> pd.DataFrame:
    """Summarize top-variable rankings using position and SHAP magnitude."""
    records = []
    for _, row in df.iterrows():
        top_vars = row.get(top_col)
        if not isinstance(top_vars, dict):
            continue
        group = {col: row[col] for col in group_cols}
        for pos, (variable, shap_abs) in enumerate(list(top_vars.items())[:top_k], start=1):
            records.append(
                {
                    **group,
                    "_var": variable,
                    "_score": float(top_k + 1 - pos) * float(shap_abs),
                }
            )

    if not records:
        return pd.DataFrame(columns=list(group_cols) + ["RELEVANCIA_VARS"])

    expanded = pd.DataFrame(records)
    scores = (
        expanded.groupby(list(group_cols) + ["_var"], dropna=False, sort=False)["_score"]
        .sum()
        .reset_index()
    )
    scores = scores.sort_values(
        list(group_cols) + ["_score"],
        ascending=[True] * len(group_cols) + [False],
        kind="stable",
    )
    scores["_rank"] = scores.groupby(list(group_cols), sort=False).cumcount()
    scores = scores[scores["_rank"] < top_k].copy()
    scores["_item"] = list(zip(scores["_var"], scores["_score"]))

    return (
        scores.groupby(list(group_cols), dropna=False, sort=False)["_item"]
        .agg(lambda items: {var: float(score) for var, score in items})
        .rename("RELEVANCIA_VARS")
        .reset_index()
    )


def assign_span_risk(tabla_vano: pd.DataFrame, *, value_col: str = "UITI_VANO") -> pd.DataFrame:
    """Assign quartile-based span risk from accumulated UITI values."""
    out = tabla_vano.copy()
    labels = ["Bajo", "Medio", "Alto", "Muy Alto"]
    if out[value_col].nunique(dropna=True) < 4:
        out["RIESGO_VANO"] = "Sin corte"
        return out
    stable_ranking = out[value_col].rank(method="first")
    out["RIESGO_VANO"] = pd.qcut(stable_ranking, q=4, labels=labels).astype(str)
    return out
