"""Unit tests for the standalone MGCECDL/SHAP simulator functions (Phase 2 of
`reporte-mgcecdl-simulator`, PR 1). These are NOT yet wired into `prepare()`/
`render()` -- that wiring is Phase 3 (PR 2). Every test here loads the REAL
production artifacts already committed under `data/` (model zip, Optuna
journal, `Variables_seleccion.xlsx`) read-only: no code path here ever fits a
model or launches an Optuna study/trial.
"""

from __future__ import annotations

import json
from pathlib import Path

from chec_local_interpreter.report_pipeline import (
    _compute_inference_scenarios,
    _load_mgcecdl_model_and_sigma,
    _modelo_mas_reciente,
)
import chec_local_interpreter.report_pipeline as report_pipeline_module


# ---------------------------------------------------------------------------
# Task 2.1 -- `_load_mgcecdl_model_and_sigma`
# ---------------------------------------------------------------------------


def test_load_mgcecdl_model_and_sigma_returns_none_none_when_model_missing(tmp_path, monkeypatch):
    empty_model_dir = tmp_path / "no-models-here"
    empty_model_dir.mkdir()
    monkeypatch.setattr(report_pipeline_module, "DEFAULT_MODEL_DIR", empty_model_dir)

    model, rbf_sigma = _load_mgcecdl_model_and_sigma()

    assert model is None
    assert rbf_sigma is None


def test_load_mgcecdl_model_and_sigma_falls_back_to_rbf_sigma_1_when_optuna_study_missing(
    tmp_path, monkeypatch
):
    missing_study_path = tmp_path / "does-not-exist.journal"
    monkeypatch.setattr(report_pipeline_module, "DEFAULT_OPTUNA_STUDY_PATH", missing_study_path)

    model, rbf_sigma = _load_mgcecdl_model_and_sigma()

    assert model is not None
    assert rbf_sigma == 1.0


def test_load_mgcecdl_model_and_sigma_loads_real_model_and_real_optuna_sigma():
    """Healthy path: both artifacts exist on disk (repo default paths) -- the
    model loads and `rbf_sigma` comes from the real Optuna study, not the
    1.0 fallback."""
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()

    assert model is not None
    assert type(model).__name__ == "MGCECDLClassifier"
    assert rbf_sigma is not None
    assert rbf_sigma != 1.0


def test_load_mgcecdl_model_and_sigma_uses_modelo_mas_reciente_resolution(tmp_path, monkeypatch):
    """Confirms the model-missing degrade path goes through the same
    `_modelo_mas_reciente` resolution ported into config.py (task 1.2) rather
    than a separate/duplicated existence check."""
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    monkeypatch.setattr(report_pipeline_module, "DEFAULT_MODEL_DIR", model_dir)

    try:
        _modelo_mas_reciente(model_dir, report_pipeline_module.DEFAULT_MODEL_BASENAME)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected _modelo_mas_reciente to raise for an empty model_dir")

    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    assert (model, rbf_sigma) == (None, None)


# ---------------------------------------------------------------------------
# Task 2.3 -- `_compute_inference_scenarios`
# ---------------------------------------------------------------------------

# BVA23L12: 20 real events, all on 2026-03-01, 20 distinct FID_VANO -- a
# single-day window with enough vanos for every percentile-based scenario
# (severity/frequency x período completo/fechas de interés) to survive.
_SUFFICIENT_CIRCUIT = "BVA23L12"
_SUFFICIENT_WINDOW = ("2026-03-01", "2026-03-01")


def test_compute_inference_scenarios_all_four_survive_with_sufficient_events(tmp_path):
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    assert model is not None, "expected the real committed model artifact to load"

    features, escenarios = _compute_inference_scenarios(
        _SUFFICIENT_CIRCUIT,
        *_SUFFICIENT_WINDOW,
        ["2026-03-01"],
        model,
        rbf_sigma,
        graph_output_dir=tmp_path / "graphs",
    )

    assert features, "features must be computed regardless of scenario survival"
    assert len(escenarios) == 4
    nombres = {escenario["nombre"] for escenario in escenarios}
    assert len(nombres) == 4, "each scenario name must be distinct"
    for escenario in escenarios:
        assert escenario["top_variables"], "a surviving scenario must have top variables"


def test_compute_inference_scenarios_partial_survival_when_dates_of_interest_dont_match(tmp_path):
    """Per-scenario skip (task 2.3): the two dates-of-interest scenarios must
    skip individually when `fechas_interes` matches nothing, while the two
    período-completo scenarios still survive -- `features` stays non-empty
    throughout (R1 gap shape, obs#219)."""
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    assert model is not None

    features, escenarios = _compute_inference_scenarios(
        _SUFFICIENT_CIRCUIT,
        *_SUFFICIENT_WINDOW,
        [],  # no dates of interest -> both fecha-based scenarios must skip
        model,
        rbf_sigma,
        graph_output_dir=tmp_path / "graphs",
    )

    assert features
    assert len(escenarios) == 2
    for escenario in escenarios:
        assert "período completo" in escenario["nombre"]


def test_compute_inference_scenarios_zero_survival_when_window_has_no_events(tmp_path):
    """R1/R3-shape edge case: a circuit/window combination with zero events
    at all -- `features` is still computed (over the full dataset) but
    `escenarios` is `[]`, and the (expensive) SHAP explainer is never built."""
    features, escenarios = _compute_inference_scenarios(
        _SUFFICIENT_CIRCUIT,
        "2020-01-01",
        "2020-01-02",
        ["2020-01-01"],
        None,  # never touched: the function must return before using `model`
        None,
        graph_output_dir=tmp_path / "graphs",
    )

    assert features, "features must be computed even when the window has zero events"
    assert escenarios == []


def test_compute_inference_scenarios_returns_r3_gap_when_model_is_none_and_window_has_events(tmp_path):
    """R3 gap: `model=None` (no MGCECDL artifact loaded) with a window that
    DOES have events must degrade gracefully -- `(features, [])` -- instead of
    crashing inside `KernelShapTopVarsExtractor.__init__` with an unguarded
    `AttributeError: 'NoneType' object has no attribute 'to'`."""
    features, escenarios = _compute_inference_scenarios(
        _SUFFICIENT_CIRCUIT,
        *_SUFFICIENT_WINDOW,
        ["2026-03-01"],
        None,
        None,
        graph_output_dir=tmp_path / "graphs",
    )

    assert features, "features must be computed even when model is None"
    assert escenarios == []


# ---------------------------------------------------------------------------
# Task 2.2 -- `SHAP_RANDOM_STATE` threaded explicitly into every
# `KernelShapTopVarsExtractor(...)` call (and the stratified-split random
# state feeding the min-max scaler) for reproducible SHAP background
# sampling: two runs on identical inputs must produce a byte-identical
# top-vars ranking.
# ---------------------------------------------------------------------------


def test_compute_inference_scenarios_is_reproducible_across_two_runs(tmp_path):
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    assert model is not None

    _features_a, escenarios_a = _compute_inference_scenarios(
        _SUFFICIENT_CIRCUIT,
        *_SUFFICIENT_WINDOW,
        ["2026-03-01"],
        model,
        rbf_sigma,
        graph_output_dir=tmp_path / "run_a",
    )
    _features_b, escenarios_b = _compute_inference_scenarios(
        _SUFFICIENT_CIRCUIT,
        *_SUFFICIENT_WINDOW,
        ["2026-03-01"],
        model,
        rbf_sigma,
        graph_output_dir=tmp_path / "run_b",
    )

    assert len(escenarios_a) == len(escenarios_b) == 4
    top_vars_a = [json.dumps(e["top_variables"], sort_keys=True) for e in escenarios_a]
    top_vars_b = [json.dumps(e["top_variables"], sort_keys=True) for e in escenarios_b]
    assert top_vars_a == top_vars_b, "top-vars ranking must be byte-identical across runs"


def test_compute_inference_scenarios_persists_graph_html_for_each_surviving_scenario(tmp_path):
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    assert model is not None
    graph_dir = tmp_path / "graphs"

    _features, escenarios = _compute_inference_scenarios(
        _SUFFICIENT_CIRCUIT,
        *_SUFFICIENT_WINDOW,
        ["2026-03-01"],
        model,
        rbf_sigma,
        graph_output_dir=graph_dir,
    )

    assert len(escenarios) == 4
    html_files = sorted(graph_dir.glob("*.html"))
    assert len(html_files) == 4
    for escenario in escenarios:
        graph_path = escenario["grafo"]["path"]
        assert graph_path is not None
        assert Path(graph_path).exists()
