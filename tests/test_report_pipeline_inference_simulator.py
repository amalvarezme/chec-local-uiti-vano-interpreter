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

import matplotlib.pyplot as plt
import pytest

from chec_impacto.interpretability.circuit_analysis import (
    graficar_barras_y_radar as _real_graficar_barras_y_radar,
)
from chec_local_interpreter.report_pipeline import (
    _compute_inference_scenarios,
    _load_mgcecdl_model_and_sigma,
    _modelo_mas_reciente,
    _run_inference_simulator,
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


# ---------------------------------------------------------------------------
# Round 2 fix -- a `ValueError` raised inside `graficar_barras_y_radar` for ONE
# scenario must: (a) skip only that scenario (the other three still survive,
# R1 gap shape, obs#219), (b) never leak the figures created before the raise,
# and (c) surface a `warnings.warn` naming the skipped scenario instead of
# silently discarding the error.
# ---------------------------------------------------------------------------


def test_compute_inference_scenarios_skips_one_scenario_on_value_error_without_leaking_or_aborting(
    tmp_path, monkeypatch
):
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    assert model is not None

    _TARGET_NOMBRE_FRAGMENT = "frecuencia — período completo"

    def _raising_for_one_scenario(eventos, nombre, *args, **kwargs):
        # Run the real implementation first so `fig_barras`/`fig_radar` are
        # actually created (mirrors a real `ValueError` raised AFTER figure
        # creation but before `graficar_barras_y_radar` returns, e.g. inside
        # graph estimation), then discard the result and raise for exactly
        # one scenario -- the other three calls pass through untouched.
        resultado = _real_graficar_barras_y_radar(eventos, nombre, *args, **kwargs)
        if _TARGET_NOMBRE_FRAGMENT in nombre:
            raise ValueError("forced failure for round-2 regression test")
        return resultado

    monkeypatch.setattr(
        report_pipeline_module, "graficar_barras_y_radar", _raising_for_one_scenario
    )

    fignums_baseline = set(plt.get_fignums())

    with pytest.warns(UserWarning, match="omitido"):
        features, escenarios = _compute_inference_scenarios(
            _SUFFICIENT_CIRCUIT,
            *_SUFFICIENT_WINDOW,
            ["2026-03-01"],
            model,
            rbf_sigma,
            graph_output_dir=tmp_path / "graphs",
        )

    assert features
    # Only the targeted scenario is skipped -- the other three still survive.
    assert len(escenarios) == 3
    nombres = {escenario["nombre"] for escenario in escenarios}
    assert not any(_TARGET_NOMBRE_FRAGMENT in nombre for nombre in nombres)

    # No figure leak: `plt.get_fignums()` returns to its pre-call baseline,
    # whether a scenario succeeded or was skipped after a `ValueError`.
    assert set(plt.get_fignums()) == fignums_baseline


# ---------------------------------------------------------------------------
# Task 3.1 -- `_run_inference_simulator` orchestration (model-missing R3 short
# circuit + R1 "all scenarios insufficient" shape). These are isolated
# orchestration-level tests: the R3/R1 *internals* of `_load_mgcecdl_model_
# and_sigma`/`_compute_inference_scenarios` are already covered above with
# real data -- these tests only need to confirm `_run_inference_simulator`
# wires them together correctly (short-circuits on model=None without ever
# touching `_compute_inference_scenarios`'s expensive real-data path, and
# resolves `modelo_label` from the real model's class name otherwise).
# ---------------------------------------------------------------------------


def test_run_inference_simulator_model_missing_returns_r3_shape_without_computing_scenarios(
    tmp_path, monkeypatch
):
    """Task 1.3 (agent-native-pipeline-and-site-split): `model`/`rbf_sigma`
    are now leading params threaded in by the caller (hoisted to `prepare()`,
    design D2) rather than loaded internally -- pass `model=None` directly
    instead of monkeypatching `_load_mgcecdl_model_and_sigma`."""

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError(
            "_compute_inference_scenarios must never be called when the model is "
            "missing (R3: 'the simulator never runs', obs#219)"
        )

    monkeypatch.setattr(
        report_pipeline_module, "_compute_inference_scenarios", _must_not_be_called
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    features, escenarios, modelo_label, rbf_sigma, render_assets = _run_inference_simulator(
        None, None, "ANY-CIRCUIT", "2026-01-01", "2026-01-01", [], run_dir
    )

    assert features == []
    assert escenarios == []
    assert modelo_label == report_pipeline_module._NO_SIMULATOR_MODEL_LABEL
    assert rbf_sigma is None
    assert render_assets == {}


class _FakeMGCECDLModel:
    """Stand-in model object so `type(model).__name__` resolves to a stable,
    real-looking class name without loading the actual (slow) artifact."""


def test_run_inference_simulator_all_scenarios_insufficient_returns_r1_shape(
    tmp_path, monkeypatch
):
    """Task 1.3: pass the fake model/sigma directly as leading params instead
    of monkeypatching `_load_mgcecdl_model_and_sigma` (dropped internal load,
    design D2)."""
    fake_model = _FakeMGCECDLModel()
    monkeypatch.setattr(
        report_pipeline_module,
        "_compute_inference_scenarios",
        lambda *args, **kwargs: (["feature_a", "feature_b"], []),
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    features, escenarios, modelo_label, rbf_sigma, render_assets = _run_inference_simulator(
        fake_model, 1.0, "ANY-CIRCUIT", "2026-01-01", "2026-01-01", [], run_dir
    )

    assert features == ["feature_a", "feature_b"], "features must be non-empty (R1 shape, obs#219)"
    assert escenarios == []
    assert modelo_label == "_FakeMGCECDLModel"
    assert rbf_sigma == 1.0
    assert render_assets == {}


# ---------------------------------------------------------------------------
# Task 3.2 -- `_run_inference_simulator` persists surviving scenarios' PNGs
# under `run_dir/inference_figures/` and HTML graphs under
# `run_dir/inference_graphs/`, and builds `render_assets` with paths relative
# to `run_dir` (never absolute).
# ---------------------------------------------------------------------------


def test_run_inference_simulator_persists_figures_with_run_dir_relative_paths(tmp_path):
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    assert model is not None, "expected the real committed model artifact to load"

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    features, escenarios, modelo_label, resolved_sigma, render_assets = _run_inference_simulator(
        model, rbf_sigma, _SUFFICIENT_CIRCUIT, *_SUFFICIENT_WINDOW, ["2026-03-01"], run_dir
    )

    assert features
    assert len(escenarios) == 4
    assert modelo_label == type(model).__name__
    assert resolved_sigma == rbf_sigma
    assert len(render_assets) == 4

    for scenario_key, asset in render_assets.items():
        for field in ("fig_barras_png", "fig_radar_png", "grafo_interactivo_html"):
            value = asset[field]
            assert value is not None, f"{scenario_key}.{field} must be set for a surviving scenario"
            assert not Path(value).is_absolute(), f"{scenario_key}.{field} must be run_dir-relative"
            resolved = (run_dir / value).resolve()
            assert resolved.exists(), f"{scenario_key}.{field} must resolve against run_dir"

    figures_dir = run_dir / "inference_figures"
    graphs_dir = run_dir / "inference_graphs"
    assert len(list(figures_dir.glob("*.png"))) == 8  # 4 scenarios x (barras + radar)
    assert len(list(graphs_dir.glob("*.html"))) == 4
