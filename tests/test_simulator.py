from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import LabelEncoder, MinMaxScaler

from chec_local_interpreter.simulator import (
    save_prioritized_variables_table,
    simulate_automatic_minmax_sensitivity,
    simulate_feature_class_transitions,
    simulate_suggested_vano_risk,
    simulate_top_softmax_curves,
    simulate_feature_values,
    transform_single_feature_value,
    validate_prioritized_variables,
)


def test_save_prioritized_variables_table_requires_non_empty(tmp_path):
    analysis = {
        "variables_a_priorizar": [
            {
                "variable": "CNT_TRF",
                "prioridad": "alta",
                "fuentes_que_la_respaldan": ["Agente predictivo"],
            }
        ]
    }
    path = tmp_path / "variables_a_priorizar.xlsx"
    saved = save_prioritized_variables_table(
        analysis,
        path,
        circuito="DON23L13",
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
    )
    df = pd.read_excel(saved)
    assert saved == path
    assert df.loc[0, "variable"] == "CNT_TRF"
    assert df.loc[0, "circuito"] == "DON23L13"


def test_validate_prioritized_variables_filters_missing_features():
    df = pd.DataFrame({"variable": ["CNT_TRF", "NO_EXISTE", "CNT_TRF"]})
    valid, warnings = validate_prioritized_variables(df, ["CNT_TRF", "CNT_VN"])
    assert valid == ["CNT_TRF"]
    assert any("NO_EXISTE" in warning for warning in warnings)


def test_transform_single_feature_value_uses_encoder_and_scaler():
    encoder = LabelEncoder().fit(["A", "B"])
    raw = np.array([[0.0, 0.0], [10.0, 1.0]], dtype=np.float32)
    scaler = MinMaxScaler().fit(raw)
    transformed = transform_single_feature_value(
        "TIPO",
        "B",
        baseline_raw_row=raw[0],
        feature_names=["CNT_TRF", "TIPO"],
        feature_scaler=scaler,
        label_encoders={"TIPO": encoder},
        max_values_imputed={},
    )
    assert transformed == 1.0


def test_simulate_feature_values_compares_against_baseline():
    feature_names = ["CNT_TRF", "CNT_VN"]
    X_raw = np.array([[0.0, 1.0], [10.0, 2.0], [5.0, 3.0]], dtype=np.float32)
    scaler = MinMaxScaler().fit(X_raw)
    X_scaled = scaler.transform(X_raw).astype(np.float32)
    original_df = pd.DataFrame({"CNT_TRF": [0.0, 10.0, 5.0], "CNT_VN": [1.0, 2.0, 3.0]})

    def predict_fn(model, X, device, batch_size=1024):
        p1 = np.clip(np.asarray(X)[:, 0], 0.0, 1.0)
        probs = np.column_stack([1.0 - p1, p1])
        return {"fused_probs": probs, "predicted_classes": probs.argmax(axis=1)}

    result, metadata = simulate_feature_values(
        model=object(),
        X_scaled=X_scaled,
        X_raw_model=X_raw,
        original_feature_df=original_df,
        feature_names=feature_names,
        variable="CNT_TRF",
        values_original=[0.0, 10.0],
        feature_scaler=scaler,
        predict_fn=predict_fn,
        device="cpu",
        class_index=1,
    )
    assert list(result["valor_original"]) == [0.0, 10.0]
    assert result.loc[0, "probabilidad_simulada"] == 0.0
    assert result.loc[1, "probabilidad_simulada"] == 1.0
    assert metadata["baseline_probabilidad_clase_objetivo"] == np.mean(X_scaled[:, 0])


def test_simulate_feature_class_transitions_reports_subset_up_and_down():
    feature_names = ["CNT_TRF", "CNT_VN"]
    X_raw = np.array([[0.0, 1.0], [10.0, 1.0]], dtype=np.float32)
    scaler = MinMaxScaler().fit(np.array([[0.0, 1.0], [10.0, 1.0]], dtype=np.float32))
    X_scaled = scaler.transform(X_raw).astype(np.float32)
    original_df = pd.DataFrame({"CNT_TRF": [0.0, 10.0], "CNT_VN": [1.0, 1.0]})

    def predict_fn(model, X, device, batch_size=1024):
        x = np.asarray(X)[:, 0]
        probs = np.zeros((len(x), 3), dtype=float)
        probs[x < 0.34, 0] = 0.8
        probs[x < 0.34, 1] = 0.15
        probs[x < 0.34, 2] = 0.05
        mid = (x >= 0.34) & (x < 0.67)
        probs[mid, 0] = 0.1
        probs[mid, 1] = 0.8
        probs[mid, 2] = 0.1
        high = x >= 0.67
        probs[high, 0] = 0.05
        probs[high, 1] = 0.15
        probs[high, 2] = 0.8
        return {"fused_probs": probs, "predicted_classes": probs.argmax(axis=1)}

    result, metadata = simulate_feature_class_transitions(
        model=object(),
        X_scaled=X_scaled,
        X_raw_model=X_raw,
        original_feature_df=original_df,
        feature_names=feature_names,
        variable="CNT_TRF",
        values_original=[0.0, 5.0, 10.0],
        feature_scaler=scaler,
        predict_fn=predict_fn,
        device="cpu",
        mask=np.array([True, True]),
    )
    assert metadata["n_filas_base"] == 2
    assert metadata["baseline_distribucion_clases"] == {"clase_0": 0.5, "clase_2": 0.5}
    assert result["direccion_cambio"].tolist() == ["baja", "igual", "sube"]
    assert result.loc[0, "pct_baja_clase"] == 0.5
    assert result.loc[1, "pct_sube_clase"] == 0.5
    assert result.loc[1, "pct_baja_clase"] == 0.5
    assert result.loc[2, "pct_sube_clase"] == 0.5
    assert result.loc[0, "probabilidad_bajar"] == pytest.approx(0.475)
    assert result.loc[2, "probabilidad_subir"] == pytest.approx(0.475)


def test_simulate_automatic_minmax_sensitivity_uses_original_extremes():
    feature_names = ["CNT_TRF", "CNT_VN"]
    X_raw = np.array([[0.0, 1.0], [10.0, 2.0], [5.0, 3.0]], dtype=np.float32)
    scaler = MinMaxScaler().fit(X_raw)
    X_scaled = scaler.transform(X_raw).astype(np.float32)
    original_df = pd.DataFrame({"CNT_TRF": [0.0, 10.0, 5.0], "CNT_VN": [1.0, 2.0, 3.0]})

    def predict_fn(model, X, device, batch_size=1024):
        x = np.asarray(X)[:, 0]
        probs = np.zeros((len(x), 3), dtype=float)
        probs[:, 0] = 1.0 - x
        probs[:, 2] = x
        return {"fused_probs": probs, "predicted_classes": probs.argmax(axis=1)}

    result, metadata = simulate_automatic_minmax_sensitivity(
        model=object(),
        X_scaled=X_scaled,
        X_raw_model=X_raw,
        original_feature_df=original_df,
        feature_names=feature_names,
        variables=["CNT_TRF", "CNT_TRF", "NO_EXISTE"],
        feature_scaler=scaler,
        predict_fn=predict_fn,
        device="cpu",
        mask=np.array([True, True, True]),
    )

    assert result["variable"].tolist() == ["CNT_TRF"]
    assert result.loc[0, "valor_minimo_usado"] == 0.0
    assert result.loc[0, "valor_maximo_usado"] == 10.0
    assert result.loc[0, "direccion_cambio_minimo"] == "disminuye riesgo"
    assert result.loc[0, "direccion_cambio_maximo"] == "aumenta riesgo"
    assert metadata["n_variables_simuladas"] == 1
    assert any("NO_EXISTE" in warning for warning in metadata["warnings"])


def test_simulate_top_softmax_curves_keeps_four_most_relevant_variables():
    feature_names = ["V1", "V2", "V3", "V4", "V5"]
    X_raw = np.array(
        [
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [10.0, 10.0, 10.0, 10.0, 10.0],
            [5.0, 5.0, 5.0, 5.0, 5.0],
        ],
        dtype=np.float32,
    )
    scaler = MinMaxScaler().fit(X_raw)
    X_scaled = scaler.transform(X_raw).astype(np.float32)
    original_df = pd.DataFrame(X_raw, columns=feature_names)
    auto_table = pd.DataFrame(
        {
            "variable": ["V5", "V2", "V4", "V1", "V3"],
            "magnitud_max_cambio_abs": [0.5, 0.4, 0.3, 0.2, 0.1],
        }
    )

    def predict_fn(model, X, device, batch_size=1024):
        x = np.clip(np.asarray(X)[:, 0], 0.0, 1.0)
        probs = np.zeros((len(x), 4), dtype=float)
        probs[:, 0] = 1.0 - x
        probs[:, 1] = x * 0.5
        probs[:, 2] = x * 0.3
        probs[:, 3] = x * 0.2
        probs = probs / probs.sum(axis=1, keepdims=True)
        return {"fused_probs": probs, "predicted_classes": probs.argmax(axis=1)}

    curves = simulate_top_softmax_curves(
        model=object(),
        X_scaled=X_scaled,
        X_raw_model=X_raw,
        original_feature_df=original_df,
        feature_names=feature_names,
        variables=feature_names,
        feature_scaler=scaler,
        predict_fn=predict_fn,
        device="cpu",
        mask=np.array([True, True, True]),
        automatic_simulation_table=auto_table,
        max_variables=4,
        max_values=3,
    )

    assert curves["metadata"]["variables_graficadas"] == ["V5", "V2", "V4", "V1"]
    assert len(curves["variables"]) == 4
    first = curves["variables"][0]
    assert first["etiquetas_clase"] == [
        "Riesgo bajo (Q1)",
        "Riesgo medio-bajo (Q2)",
        "Riesgo medio-alto (Q3)",
        "Riesgo alto (Q4)",
    ]
    assert first["mejor_escenario_menor_riesgo"]["clase_estimacion"] in {
        "Riesgo bajo (Q1)",
        "Riesgo medio-bajo (Q2)",
    }


def test_simulate_suggested_vano_risk_averages_probabilities_by_vano():
    feature_names = ["CNT_TRF", "CNT_VN"]
    X_raw = np.array(
        [
            [0.0, 1.0],
            [10.0, 2.0],
            [5.0, 3.0],
        ],
        dtype=np.float32,
    )
    scaler = MinMaxScaler().fit(X_raw)
    X_scaled = scaler.transform(X_raw).astype(np.float32)

    def predict_fn(model, X, device, batch_size=1024):
        values = np.clip(np.asarray(X)[:, 0], 0.0, 1.0)
        probs = np.column_stack(
            [
                1.0 - values,
                values * 0.6,
                values * 0.3,
                values * 0.1,
            ]
        )
        probs = probs / probs.sum(axis=1, keepdims=True)
        return {"fused_probs": probs, "predicted_classes": probs.argmax(axis=1)}

    curves = {
        "variables": [
            {
                "variable": "CNT_TRF",
                "filas": [
                    {
                        "valor_original": 0.0,
                        "riesgo_ordinal_estimado": 0.0,
                        "probabilidades": {
                            "Riesgo bajo (Q1)": 0.9,
                            "Riesgo medio-bajo (Q2)": 0.1,
                        },
                    }
                ],
            }
        ]
    }

    result, metadata = simulate_suggested_vano_risk(
        model=object(),
        X_scaled=X_scaled,
        X_raw_model=X_raw,
        feature_names=feature_names,
        feature_scaler=scaler,
        predict_fn=predict_fn,
        device="cpu",
        mask=np.array([True, True, True]),
        vano_ids=pd.Series(["V1", "V1", "V2"]),
        softmax_curves=curves,
    )

    v1 = result[result["FID_VANO"] == "V1"].iloc[0]
    assert v1["n_registros"] == 2
    assert v1["simulado_clase"] == "Riesgo bajo (Q1)"
    assert v1["variables_aplicadas"] == "CNT_TRF"
    assert metadata["agregacion"] == "promedio_probabilidades_por_vano"
