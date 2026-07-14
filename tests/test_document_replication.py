from __future__ import annotations

import json

import numpy as np
import pandas as pd

from chec_impacto.interpretability.document_replication import (
    aggregate_weighted_borda,
    assign_span_risk,
    build_top_vars_with_values,
    scalar_python,
    serialize_dict_columns,
)


def test_scalar_python_normalizes_pandas_and_numpy_values():
    assert scalar_python(pd.Timestamp("2026-07-13")) == "2026-07-13T00:00:00"
    assert scalar_python(np.int64(7)) == 7
    assert scalar_python(np.nan) is None


def test_serialize_dict_columns_converts_dicts_to_json_strings():
    df = pd.DataFrame({"payload": [{"b": np.int64(2)}, None], "value": [1, 2]})

    result = serialize_dict_columns(df)

    assert json.loads(result.loc[0, "payload"]) == {"b": 2}
    assert result.loc[1, "payload"] is None
    assert result["value"].tolist() == [1, 2]


def test_build_top_vars_with_values_limits_top_k_and_preserves_missing_values():
    row = pd.Series({"A": 10, "_TOP_VARS": {"A": 0.5, "B": 0.25}})

    result = build_top_vars_with_values(row, top_k=2)

    assert result == {
        "A": {"valor_original": 10, "relevancia_mgcecdl": 0.5},
        "B": {"valor_original": None, "relevancia_mgcecdl": 0.25},
    }


def test_aggregate_weighted_borda_sums_position_weighted_scores():
    df = pd.DataFrame(
        {
            "FID_VANO": ["V1", "V1", "V2"],
            "_TOP_VARS": [
                {"A": 1.0, "B": 0.5},
                {"B": 2.0, "A": 0.25},
                None,
            ],
        }
    )

    result = aggregate_weighted_borda(df, ["FID_VANO"], top_k=2)

    row = result[result["FID_VANO"] == "V1"].iloc[0]
    assert row["RELEVANCIA_VARS"] == {"B": 4.5, "A": 2.25}


def test_assign_span_risk_uses_quartiles_when_enough_unique_values():
    df = pd.DataFrame({"UITI_VANO": [1, 2, 3, 4]})

    result = assign_span_risk(df)

    assert result["RIESGO_VANO"].tolist() == ["Bajo", "Medio", "Alto", "Muy Alto"]


def test_assign_span_risk_uses_sin_corte_when_not_enough_unique_values():
    df = pd.DataFrame({"UITI_VANO": [1, 1, 2]})

    result = assign_span_risk(df)

    assert result["RIESGO_VANO"].tolist() == ["Sin corte", "Sin corte", "Sin corte"]
