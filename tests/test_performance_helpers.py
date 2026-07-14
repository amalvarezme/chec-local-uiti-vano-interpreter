from __future__ import annotations

import numpy as np

from chec_impacto.interpretability.performance import (
    absolute_shap_matrix,
    build_shap_predict_fn,
    expand_selected_variables,
)


def test_expand_selected_variables_expands_climate_prefixes():
    result = expand_selected_variables(
        ["FECHA", "prep", "UITI_VANO", "missing"],
        selected_names={"FECHA", "prep", "UITI_VANO", "missing"},
        features=["FECHA", "prep_0", "prep_1", "temp_0"],
        climate_prefixes={"prep", "temp"},
    )

    assert result == ["FECHA", "prep_0", "prep_1"]


def test_absolute_shap_matrix_handles_list_and_3d_layouts():
    list_values = [np.array([[1.0, -2.0]]), np.array([[-3.0, 4.0]])]
    assert absolute_shap_matrix(list_values, 2).tolist() == [[2.0, 3.0]]

    values = np.array([[[1.0, -2.0], [3.0, -5.0]]])
    assert absolute_shap_matrix(values, 2).tolist() == [[1.5, 4.0]]


def test_build_shap_predict_fn_pads_singleton_batch_and_returns_single_row():
    captured = {}

    def fake_predict(model, values, *, device):
        captured["values"] = values
        captured["device"] = device
        return {"fused_probs": np.array([[0.2, 0.8], [0.6, 0.4]])}

    predict = build_shap_predict_fn(object(), np.array([[9, 9, 9]], dtype=np.float32), fake_predict, device="cpu")

    result = predict([1, 2, 3])

    assert result.tolist() == [[0.2, 0.8]]
    assert captured["values"].shape == (2, 3)
    assert captured["device"] == "cpu"
