from __future__ import annotations

import numpy as np

from chec_impacto.interpretability import circuit_analysis
from chec_impacto.interpretability.circuit_analysis import MGCECDLClassifierShapAdapter
from chec_impacto.training import checkpoint_path, latest_model_path


def test_latest_model_path_selects_last_sorted_candidate(tmp_path):
    older = tmp_path / "mgcecdl_classifier_best.zip"
    newer = tmp_path / "mgcecdl_classifier_best_20260713_1000.zip"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")

    assert latest_model_path(tmp_path, "mgcecdl_classifier_best.zip") == newer


def test_checkpoint_path_adds_timestamp_when_base_exists(tmp_path):
    base = tmp_path / "model.zip"
    base.write_text("existing", encoding="utf-8")

    assert checkpoint_path(base, timestamp="20260713_1015") == tmp_path / "model_20260713_1015.zip"


def test_checkpoint_path_returns_base_when_missing(tmp_path):
    base = tmp_path / "model.zip"

    assert checkpoint_path(base, timestamp="20260713_1015") == base


def test_mgcecdl_classifier_shap_adapter_returns_2d_float_probabilities(monkeypatch):
    captured = {}

    def fake_predict_classification(model, values, *, device):
        captured["model"] = model
        captured["values"] = values
        captured["device"] = device
        return {"fused_probs": [[0.25, 0.75]]}

    monkeypatch.setattr(circuit_analysis, "predict_classification", fake_predict_classification)
    model = object()
    adapter = MGCECDLClassifierShapAdapter(model, device="cpu")

    result = adapter.predict_proba([1, 2, 3])

    assert result.dtype == np.float64
    assert result.shape == (1, 2)
    assert captured["model"] is model
    assert captured["device"] == "cpu"
    assert captured["values"].dtype == np.float32
    assert captured["values"].shape == (1, 3)
