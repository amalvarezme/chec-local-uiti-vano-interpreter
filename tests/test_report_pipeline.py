from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import chec_local_interpreter.report_pipeline as report_pipeline_module
from chec_local_interpreter.config import DEFAULT_MODEL_DIR as _REAL_DEFAULT_MODEL_DIR
from chec_local_interpreter.inference_validation import validar_respuesta_inferencia_strict
from chec_local_interpreter.report_pipeline import (
    ReportPipelineError,
    prepare,
    prepare_expert_alignment,
    render,
)


@pytest.fixture(autouse=True)
def _no_real_mgcecdl_model_by_default(tmp_path, monkeypatch):
    """Most tests in this file use a small synthetic fixture dataset (C1/C2)
    that is NOT compatible with the real MGCECDL simulator's
    `Variables_seleccion.xlsx` feature-column requirements (confirmed
    empirically: `procesar_dataset_completo` raises `ValueError` for this
    fixture's columns). Point `_load_mgcecdl_model_and_sigma` at an empty
    model directory by default so `prepare()`'s simulator step degrades to
    the spec'd "missing trained model" gap (R3, obs#219) instead of crashing
    on an incompatible dataset -- the same "no simulator output" shape these
    tests already asserted against the old stub.

    Tests that need the REAL simulator (the integration tests in the
    "real inference simulator" section below) explicitly restore the real
    `DEFAULT_MODEL_DIR` via `monkeypatch.setattr(...)` after this fixture
    runs -- `monkeypatch` preserves call order, so the later, more specific
    patch wins for the duration of that test.
    """
    empty_model_dir = tmp_path / "no-mgcecdl-model"
    empty_model_dir.mkdir()
    monkeypatch.setattr(report_pipeline_module, "DEFAULT_MODEL_DIR", empty_model_dir)


def _write_fixture_dataset(directory: Path) -> Path:
    """A 10-day window for circuit C1 with one clear spike day, plus an
    unrelated circuit C2 in a disjoint window (so C1-only filtering and
    circuit-presence checks are both exercised)."""
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    rows = []
    for index, date in enumerate(dates):
        rows.append(
            {
                "CIRCUITO": "C1",
                "FECHA": date.strftime("%Y-%m-%d"),
                "UITI_VANO": 60.0 if index == 5 else 4.0,
                "FID_VANO": f"V{index}",
                "DESC_CAUSA": "Viento",
            }
        )
    rows.append(
        {"CIRCUITO": "C2", "FECHA": "2026-06-01", "UITI_VANO": 1.0, "FID_VANO": "V99", "DESC_CAUSA": "Otro"}
    )
    frame = pd.DataFrame(rows)
    csv_path = directory / "dataset.csv"
    frame.to_csv(csv_path, index=False)
    return csv_path


def _canned_ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# prepare()
# ---------------------------------------------------------------------------


def test_prepare_happy_path_no_dates_uses_full_circuit_range(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)

    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")

    assert run_dir.is_dir()
    assert (run_dir / "historical.bc.json").exists()
    assert (run_dir / "inference.bc.json").exists()
    assert (run_dir / "l1_state.json").exists()

    state = _read_json(run_dir / "l1_state.json")
    assert state["circuito"] == "C1"
    assert state["fecha_inicio"] == "2026-01-01"
    assert state["fecha_fin"] == "2026-01-10"
    assert state["critical_points"], "expected at least one critical point from the spike day"

    historical_context = _read_json(run_dir / "historical.bc.json")
    # Graphify has no backend configured in the test environment; confirm the
    # existing context_builder degradation path produced a string instead of
    # raising (task 6.8 — orchestrator must not catch this earlier/later).
    assert isinstance(historical_context["graph_knowledge"], str)

    inference_context = _read_json(run_dir / "inference.bc.json")
    assert inference_context["circuito_interes"] == "C1"
    assert inference_context["fecha_inicio"] == "2026-01-01"
    assert inference_context["fecha_fin"] == "2026-01-10"


def test_prepare_wires_real_simulator_stub_replaced_by_r3_gap_when_model_missing(tmp_path):
    """Task 3.3: `prepare()` no longer hardcodes `features=[]`/`escenarios=[]`/
    `_NO_SIMULATOR_MODEL_LABEL` -- it now calls `_run_inference_simulator`.
    With the (default, autoused) empty model dir, this must reach the exact
    same R3 gap shape the old stub always produced (obs#219): `features=[]`,
    `escenarios=[]`, `modelo=_NO_SIMULATOR_MODEL_LABEL` -- and no render-assets
    sidecar (nothing to persist when the simulator never ran)."""
    data_path = _write_fixture_dataset(tmp_path)

    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")

    inference_context = _read_json(run_dir / "inference.bc.json")
    assert inference_context["features"] == []
    assert inference_context["escenarios"] == []
    assert inference_context["modelo"] == report_pipeline_module._NO_SIMULATOR_MODEL_LABEL
    assert not (run_dir / "inference_render_assets.json").exists()


def test_prepare_creates_run_dir_after_zero_events_check_before_simulator(tmp_path, monkeypatch):
    """Task 3.3: `_new_run_dir(...)` must run AFTER the zero-events hard-fail
    check but BEFORE the simulator call, so a simulator-side exception could
    never leave callers without a `run_dir` reference, while hard failures
    (circuit-not-found/zero-events) still never create one."""
    data_path = _write_fixture_dataset(tmp_path)
    runs_root = tmp_path / "runs"

    calls: list[str] = []
    original_new_run_dir = report_pipeline_module._new_run_dir
    original_run_inference_simulator = report_pipeline_module._run_inference_simulator

    def _tracking_new_run_dir(*args, **kwargs):
        calls.append("_new_run_dir")
        return original_new_run_dir(*args, **kwargs)

    def _tracking_run_inference_simulator(*args, **kwargs):
        calls.append("_run_inference_simulator")
        return original_run_inference_simulator(*args, **kwargs)

    monkeypatch.setattr(report_pipeline_module, "_new_run_dir", _tracking_new_run_dir)
    monkeypatch.setattr(
        report_pipeline_module, "_run_inference_simulator", _tracking_run_inference_simulator
    )

    prepare("C1", data_path=data_path, runs_root=runs_root)

    assert calls == ["_new_run_dir", "_run_inference_simulator"]


def test_prepare_explicit_dates_are_respected(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)

    run_dir = prepare(
        "C1", "2026-01-02", "2026-01-04", data_path=data_path, runs_root=tmp_path / "runs"
    )

    state = _read_json(run_dir / "l1_state.json")
    assert state["fecha_inicio"] == "2026-01-02"
    assert state["fecha_fin"] == "2026-01-04"


def test_prepare_circuit_not_found_fails_fast_before_any_agent(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    runs_root = tmp_path / "runs"

    with pytest.raises(ReportPipelineError, match="not found"):
        prepare("does-not-exist", data_path=data_path, runs_root=runs_root)

    assert not runs_root.exists()


def test_prepare_zero_events_in_window_fails_fast(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    runs_root = tmp_path / "runs"

    with pytest.raises(ReportPipelineError, match="No events"):
        prepare("C1", "2030-01-01", "2030-02-01", data_path=data_path, runs_root=runs_root)

    assert not runs_root.exists()


# ---------------------------------------------------------------------------
# `/reporte` argument-pair contract (Phase 7): `fecha_inicio`/`fecha_fin` are a
# PAIR — both given or both omitted. Exactly one given is a usage error, never
# silently defaulted by treating the missing bound as absent.
# ---------------------------------------------------------------------------


def test_prepare_rejects_lone_fecha_inicio_without_fecha_fin(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    runs_root = tmp_path / "runs"

    with pytest.raises(ReportPipelineError, match="pair"):
        prepare("C1", "2026-01-02", None, data_path=data_path, runs_root=runs_root)

    assert not runs_root.exists()


def test_prepare_rejects_lone_fecha_fin_without_fecha_inicio(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    runs_root = tmp_path / "runs"

    with pytest.raises(ReportPipelineError, match="pair"):
        prepare("C1", None, "2026-01-04", data_path=data_path, runs_root=runs_root)

    assert not runs_root.exists()


# ---------------------------------------------------------------------------
# prepare_expert_alignment()
# ---------------------------------------------------------------------------


def test_prepare_expert_alignment_builds_bc_json_from_canned_validated_outputs(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")

    (run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico."]})), encoding="utf-8"
    )
    (run_dir / "inference.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo de inferencia."]})), encoding="utf-8"
    )

    result = prepare_expert_alignment(run_dir)

    assert result == run_dir
    assert (run_dir / "expert-alignment.bc.json").exists()
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["circuito"] == "C1"


def test_prepare_expert_alignment_missing_historical_output_stops_before_expert_alignment_bc(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    # inference.out.json also intentionally absent: historical is checked first.

    with pytest.raises(ReportPipelineError, match="historical"):
        prepare_expert_alignment(run_dir)

    assert not (run_dir / "expert-alignment.bc.json").exists()


def test_prepare_expert_alignment_schema_guardrail_invalid_after_max_retries_stops_before_render(tmp_path):
    """Simulates retries-exhausted: the Skill never wrote historical.out.json
    because `validate` kept returning exit 1 up to MAX_VALIDATION_RETRIES.
    `prepare_expert_alignment` must fail identically to the missing-file case
    above — it never has a validated envelope to build from."""
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(
        json.dumps({"ok": False, "errors": ["schema: campo requerido faltante"]}), encoding="utf-8"
    )
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": []})), encoding="utf-8")

    with pytest.raises(ReportPipelineError, match="historical"):
        prepare_expert_alignment(run_dir)

    assert not (run_dir / "expert-alignment.bc.json").exists()


def test_prepare_expert_alignment_provenance_invalid_after_schema_pass_hard_stops_identically(tmp_path):
    """Provenance-only failure (schema/guardrails passed) must be treated
    identically to a schema failure by this orchestrator layer — both are
    just `ok: false` from the combined L1 `validate()` contract, so they
    consume exactly one retry attempt each at the Skill/CLI layer and look
    the same here."""
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(
        json.dumps({"ok": False, "errors": ["provenance: data_ref fuera del universo permitido"]}),
        encoding="utf-8",
    )
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": []})), encoding="utf-8")

    with pytest.raises(ReportPipelineError, match="historical"):
        prepare_expert_alignment(run_dir)

    assert not (run_dir / "expert-alignment.bc.json").exists()


# ---------------------------------------------------------------------------
# render()
# ---------------------------------------------------------------------------


def test_render_produces_html_file_from_canned_validated_envelopes(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["H1"]})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["I1"]})), encoding="utf-8")
    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )

    html_path = render(run_dir, output_dir=tmp_path / "html")

    assert html_path.exists()
    assert html_path.suffix == ".html"
    assert html_path.read_text(encoding="utf-8").strip() != ""


def test_render_sidecar_absent_inference_results_stays_none_no_crash(tmp_path, monkeypatch):
    """Task 3.4: with the (default, autoused) empty model dir, prepare() never
    writes `inference_render_assets.json` -- `render()` must pass
    `inference_results=None` (same as before wiring) rather than crashing."""
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    assert not (run_dir / "inference_render_assets.json").exists()
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["H1"]})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["I1"]})), encoding="utf-8")
    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured["inference_results"] = kwargs.get("inference_results")
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html")

    assert captured["inference_results"] is None


def test_render_sidecar_present_builds_non_none_inference_results(tmp_path, monkeypatch):
    """Task 3.4: when `inference_render_assets.json` exists, `render()` must
    resolve each path against `run_dir` and rebuild `inference_results`
    (keyed by scenario key, each `{fig_barras, fig_radar, grafo_interactivo,
    contexto}`) instead of passing `None`."""
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["H1"]})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["I1"]})), encoding="utf-8")
    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )

    # Simulate what a healthy `_run_inference_simulator` run would have
    # written: a matching scenario contexto in inference.bc.json plus the
    # sidecar + the (fake) persisted PNG/HTML files it references.
    scenario_nombre = "Top P97 por UITI_VANO — período completo"
    inference_bc = _read_json(run_dir / "inference.bc.json")
    inference_bc["escenarios"] = [{"nombre": scenario_nombre, "criterio": "x"}]
    (run_dir / "inference.bc.json").write_text(json.dumps(inference_bc), encoding="utf-8")

    (run_dir / "inference_figures").mkdir()
    (run_dir / "inference_figures" / "top_uiti_periodo_barras.png").write_bytes(b"fakepng")
    (run_dir / "inference_figures" / "top_uiti_periodo_radar.png").write_bytes(b"fakepng")
    (run_dir / "inference_graphs").mkdir()
    (run_dir / "inference_graphs" / "top_uiti_periodo.html").write_text("<html></html>", encoding="utf-8")

    render_assets = {
        "top_uiti_periodo": {
            "nombre": scenario_nombre,
            "fig_barras_png": "inference_figures/top_uiti_periodo_barras.png",
            "fig_radar_png": "inference_figures/top_uiti_periodo_radar.png",
            "grafo_interactivo_html": "inference_graphs/top_uiti_periodo.html",
        }
    }
    (run_dir / "inference_render_assets.json").write_text(json.dumps(render_assets), encoding="utf-8")

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured["inference_results"] = kwargs.get("inference_results")
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html")

    inference_results = captured["inference_results"]
    assert inference_results is not None
    assert set(inference_results.keys()) == {"top_uiti_periodo"}
    entry = inference_results["top_uiti_periodo"]
    assert entry["fig_barras"] == str(run_dir / "inference_figures" / "top_uiti_periodo_barras.png")
    assert entry["fig_radar"] == str(run_dir / "inference_figures" / "top_uiti_periodo_radar.png")
    assert entry["grafo_interactivo"] == str(run_dir / "inference_graphs" / "top_uiti_periodo.html")
    assert entry["contexto"]["nombre"] == scenario_nombre


def test_render_missing_expert_alignment_output_raises_before_writing_html(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({})), encoding="utf-8")
    prepare_expert_alignment(run_dir)
    output_dir = tmp_path / "html"

    with pytest.raises(ReportPipelineError, match="expert-alignment"):
        render(run_dir, output_dir=output_dir)

    assert not output_dir.exists()


# ---------------------------------------------------------------------------
# Full run-dir handoff integration (task 6.7) — no live LLM call anywhere.
# ---------------------------------------------------------------------------


def test_full_run_dir_handoff_prepare_to_render(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)

    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["H"]})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["I"]})), encoding="utf-8")

    run_dir_after_ea = prepare_expert_alignment(run_dir)
    assert run_dir_after_ea == run_dir
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "S"})), encoding="utf-8"
    )

    html_path = render(run_dir, output_dir=tmp_path / "html")

    assert html_path.exists()


# ---------------------------------------------------------------------------
# prepare_expert_alignment() — real PDF-discussion wiring (fix for the
# hardcoded-empty bug: the xlsx table BUILT by the out-of-scope extraction
# notebook must still be read and matched against the circuit here).
# ---------------------------------------------------------------------------


def _write_pdf_discussions_xlsx(path: Path, rows: list[dict]) -> Path:
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def _prepare_with_canned_agent_outputs(tmp_path: Path) -> Path:
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico."]})), encoding="utf-8"
    )
    (run_dir / "inference.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo de inferencia."]})), encoding="utf-8"
    )
    return run_dir


def test_prepare_expert_alignment_wires_real_pdf_matches_for_matching_circuit(tmp_path):
    run_dir = _prepare_with_canned_agent_outputs(tmp_path)
    # The fixture dataset's spike/critical day falls inside 2026-01-01..2026-01-10;
    # this row's interval overlaps that window for circuit C1.
    xlsx_path = _write_pdf_discussions_xlsx(
        tmp_path / "tabla_pdfs_intervalo_test.xlsx",
        [
            {
                "Circuito": "C1",
                "Fecha inicio": "2026-01-05",
                "Fecha fin": "2026-01-07",
                "Análisis": "Análisis experto sobre el pico de C1.",
                "Evidencia": "Evidencia documentada en el informe experto.",
            }
        ],
    )

    result = prepare_expert_alignment(run_dir, pdf_discussions_path=xlsx_path)

    assert result == run_dir
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["pdf_expert_matches"], "expected at least one temporal PDF match for circuit C1"
    assert bc["pdf_expert_matches"][0]["Circuito"] == "C1"
    assert bc["modelo_experto_disponible"] is True


def test_prepare_expert_alignment_pools_fechas_informe_from_all_sources(tmp_path):
    run_dir = _prepare_with_canned_agent_outputs(tmp_path)

    result = prepare_expert_alignment(run_dir, pdf_discussions_path=tmp_path / "does-not-exist.xlsx")

    assert result == run_dir
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["fechas_informe"], "fechas_informe must be pooled, not left empty"
    sources = {record["source"] for record in bc["fechas_informe"]}
    # At minimum the critical-point-derived date and the global report window
    # must be present — confirms pooling from critical points + period bounds,
    # not just a hardcoded empty list.
    assert "critical_point" in sources
    assert "context" in sources


def test_prepare_expert_alignment_missing_pdf_file_degrades_gracefully(tmp_path):
    run_dir = _prepare_with_canned_agent_outputs(tmp_path)

    result = prepare_expert_alignment(run_dir, pdf_discussions_path=tmp_path / "does-not-exist.xlsx")

    assert result == run_dir
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["pdf_expert_matches"] == []
    assert bc["modelo_experto_disponible"] is False


def test_prepare_expert_alignment_empty_pdf_table_degrades_gracefully(tmp_path):
    run_dir = _prepare_with_canned_agent_outputs(tmp_path)
    xlsx_path = _write_pdf_discussions_xlsx(
        tmp_path / "tabla_pdfs_intervalo_empty.xlsx",
        [
            {
                "Circuito": "",
                "Fecha inicio": None,
                "Fecha fin": None,
                "Análisis": "",
                "Evidencia": "",
            }
        ],
    )

    result = prepare_expert_alignment(run_dir, pdf_discussions_path=xlsx_path)

    assert result == run_dir
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["pdf_expert_matches"] == []
    assert bc["modelo_experto_disponible"] is False


def test_prepare_expert_alignment_zero_rows_for_circuit_degrades_gracefully(tmp_path):
    run_dir = _prepare_with_canned_agent_outputs(tmp_path)
    xlsx_path = _write_pdf_discussions_xlsx(
        tmp_path / "tabla_pdfs_intervalo_other_circuit.xlsx",
        [
            {
                "Circuito": "OTHER-CIRCUIT",
                "Fecha inicio": "2026-01-05",
                "Fecha fin": "2026-01-07",
                "Análisis": "Análisis de un circuito distinto.",
                "Evidencia": "Evidencia no relacionada con C1.",
            }
        ],
    )

    result = prepare_expert_alignment(run_dir, pdf_discussions_path=xlsx_path)

    assert result == run_dir
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["pdf_expert_matches"] == []
    assert bc["modelo_experto_disponible"] is False


# ---------------------------------------------------------------------------
# Final Slice B / whole-change gate (task 8.2): end-to-end `/reporte` smoke
# check as close to real as the harness allows without a live LLM call --
# `prepare` -> canned validated agent outputs -> `prepare_expert_alignment`
# (with REAL PDF-discussion matching, not an empty table) -> canned
# expert-alignment output -> `render` -> a real, non-empty HTML file.
# Reuses the existing fixture-dataset/xlsx helpers above rather than inventing
# new large fixture data.
# ---------------------------------------------------------------------------


def test_reporte_end_to_end_smoke_produces_html_with_real_pdf_matches(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    xlsx_path = _write_pdf_discussions_xlsx(
        tmp_path / "tabla_pdfs_intervalo_smoke.xlsx",
        [
            {
                "Circuito": "C1",
                "Fecha inicio": "2026-01-05",
                "Fecha fin": "2026-01-07",
                "Análisis": "Análisis experto sobre el pico de C1 (smoke test).",
                "Evidencia": "Evidencia documentada en el informe experto.",
            }
        ],
    )

    # Step 1: prepare() -- circuit only, no dates, mirrors `/reporte C1`.
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    assert (run_dir / "historical.bc.json").exists()
    assert (run_dir / "inference.bc.json").exists()

    # Step 2/3: canned validated outputs, standing in for the interactive
    # `historical` and `inference` Skills (no live LLM call in this harness).
    (run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico de humo."]})), encoding="utf-8"
    )
    (run_dir / "inference.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo de inferencia de humo."]})), encoding="utf-8"
    )

    # Step 4: prepare_expert_alignment() -- real PDF-discussion matching wired.
    run_dir_after_ea = prepare_expert_alignment(run_dir, pdf_discussions_path=xlsx_path)
    assert run_dir_after_ea == run_dir
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["pdf_expert_matches"], "expected the smoke fixture's PDF match to be wired through"
    assert bc["modelo_experto_disponible"] is True

    # Step 5: canned validated expert-alignment output, standing in for the
    # interactive `expert-alignment` Skill.
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado (smoke test)."})), encoding="utf-8"
    )

    # Step 6: render() -- the actual HTML report artifact `/reporte` returns.
    html_path = render(run_dir, output_dir=tmp_path / "html")

    assert html_path.exists()
    assert html_path.suffix == ".html"
    html_content = html_path.read_text(encoding="utf-8")
    assert html_content.strip() != ""
    assert "C1" in html_content


def test_prepare_expert_alignment_default_path_resolves_via_glob(tmp_path, monkeypatch):
    import chec_local_interpreter.report_pipeline as report_pipeline_module

    run_dir = _prepare_with_canned_agent_outputs(tmp_path)
    discussions_dir = tmp_path / "analysis-documents"
    discussions_dir.mkdir()
    # Two candidates matching the glob; the resolver must deterministically
    # pick exactly one (most recent by sorted name) rather than crashing.
    _write_pdf_discussions_xlsx(
        discussions_dir / "tabla_pdfs_intervalo_2025-01-01_2025-06-30.xlsx",
        [
            {
                "Circuito": "C1",
                "Fecha inicio": "2025-01-05",
                "Fecha fin": "2025-01-07",
                "Análisis": "Tabla antigua.",
                "Evidencia": "No debe usarse.",
            }
        ],
    )
    _write_pdf_discussions_xlsx(
        discussions_dir / "tabla_pdfs_intervalo_2025-11-01_2026-04-30.xlsx",
        [
            {
                "Circuito": "C1",
                "Fecha inicio": "2026-01-05",
                "Fecha fin": "2026-01-07",
                "Análisis": "Tabla vigente.",
                "Evidencia": "Debe usarse esta.",
            }
        ],
    )
    monkeypatch.setattr(report_pipeline_module, "DEFAULT_PDF_DISCUSSIONS_DIR", discussions_dir)

    result = prepare_expert_alignment(run_dir)

    assert result == run_dir
    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert bc["pdf_expert_matches"], "expected the glob-resolved xlsx to be picked up by default"
    assert bc["pdf_expert_matches"][0]["Análisis"] == "Tabla vigente."


# ---------------------------------------------------------------------------
# Real inference simulator integration (tasks 4.1-4.3). Unlike the rest of
# this file, these tests use the REAL committed model/Optuna/Variables
# artifacts on a real circuit with sufficient events -- explicitly restoring
# `DEFAULT_MODEL_DIR` (the autouse fixture above defaults it to empty).
# ---------------------------------------------------------------------------

# BVA23L12, 2026-03-01: same real circuit/window PR1's own tests already use
# (tests/test_report_pipeline_inference_simulator.py) -- 20 real events, all
# four scenario types survive.
_REAL_SUFFICIENT_CIRCUIT = "BVA23L12"
_REAL_SUFFICIENT_WINDOW = ("2026-03-01", "2026-03-01")


def _enable_real_mgcecdl_model(monkeypatch) -> None:
    monkeypatch.setattr(report_pipeline_module, "DEFAULT_MODEL_DIR", _REAL_DEFAULT_MODEL_DIR)


def _canned_inference_ok(run_dir: Path) -> dict:
    """Task 4.2: build a canned VALIDATED `inference.out.json` payload whose
    `escenarios[].nombre` values are read FROM the real
    `run_dir/inference.bc.json` (never hand-written), then run it through the
    real `validar_respuesta_inferencia_strict` so
    `inference_validation.py`'s `allowed_scenario_names`/`_guardrail_errors`
    are actually exercised end to end rather than bypassed."""
    inference_bc = _read_json(run_dir / "inference.bc.json")
    escenario_nombres = [
        escenario["nombre"]
        for escenario in inference_bc.get("escenarios", [])
        if isinstance(escenario, dict) and escenario.get("nombre")
    ]
    graph_paths_by_nombre = {
        item.get("escenario"): item.get("path")
        for item in inference_bc.get("graph_html_paths", [])
        if isinstance(item, dict)
    }

    response = {
        "contexto": {
            "circuito": inference_bc["circuito_interes"],
            "periodo": {"inicio": inference_bc["fecha_inicio"], "fin": inference_bc["fecha_fin"]},
            "modelo": inference_bc["modelo"],
        },
        "entregables": {
            "grafos_html": [
                {
                    "escenario": nombre,
                    "path": graph_paths_by_nombre.get(nombre) or "grafo.html",
                    "fuente": "reconstruccion_mgcecdl_rbf",
                    "pesos": "normalizados_0_1_por_maximo",
                }
                for nombre in escenario_nombres
            ]
        },
        "escenarios": [
            {"nombre": nombre, "interpretacion": f"Interpretacion generada para pruebas: {nombre}."}
            for nombre in escenario_nombres
        ],
        "discusion_grafos": (
            [
                {
                    "seccion": "periodo_completo",
                    "lectura": "Discusion de grafo generada para pruebas de integracion.",
                }
            ]
            if escenario_nombres
            else []
        ),
        "coherencia_grafo_modelo": ["Coherencia generada para pruebas de integracion."],
        "hallazgos": (
            [f"Hallazgo generado para pruebas: {nombre}." for nombre in escenario_nombres]
            if escenario_nombres
            else ["Sin hallazgos: no hay escenarios sobrevivientes en este contexto."]
        ),
        "limitaciones": ["Limitacion generada para pruebas de integracion."],
        "inferencias_predictivas": [],
        "hipotesis_modelo_predictivo": {"periodo_completo": [], "puntos_criticos": []},
    }

    validated = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), inference_bc)
    assert validated["ok"], validated["errors"]
    return {"ok": True, "data": validated["data"]}


def test_prepare_wires_real_inference_simulator_with_sufficient_events(tmp_path, monkeypatch):
    """Task 4.1: real prepare() with the real model+Optuna+Variables
    artifacts and a circuit/window with sufficient events -- non-empty
    features, >=1 escenario, and the PNGs/HTML/sidecar this change persists
    under run_dir."""
    _enable_real_mgcecdl_model(monkeypatch)

    run_dir = prepare(
        _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
    )

    inference_context = _read_json(run_dir / "inference.bc.json")
    assert inference_context["features"], "expected real features from the real simulator"
    assert len(inference_context["escenarios"]) >= 1
    assert inference_context["modelo"] != report_pipeline_module._NO_SIMULATOR_MODEL_LABEL

    sidecar_path = run_dir / "inference_render_assets.json"
    assert sidecar_path.exists()
    render_assets = _read_json(sidecar_path)
    assert render_assets

    figures_dir = run_dir / "inference_figures"
    graphs_dir = run_dir / "inference_graphs"
    assert list(figures_dir.glob("*.png")), "expected persisted fig_barras/fig_radar PNGs"
    assert list(graphs_dir.glob("*.html")), "expected persisted grafo_interactivo HTML"


def test_prepare_survives_persistence_failure_for_one_scenario_keeps_others_and_completes(
    tmp_path, monkeypatch
):
    """Persistence-layer failure (`OSError`) while saving one scenario's
    render assets (PNG/HTML) must NOT discard that scenario's already-
    computed `contexto`, must NOT crash `prepare()`, and must be reported
    with wording distinct from the "omitido por ValueError"/insufficient-
    signal warning -- the run always continues and the report always
    generates (per the reporte Skill's documented degrade contract)."""
    _enable_real_mgcecdl_model(monkeypatch)

    original_persist = report_pipeline_module._persist_scenario_render_assets
    _FAILING_SCENARIO_KEY = "top_frecuencia_periodo"
    failed_calls: list[str] = []

    def _persist_failing_for_one_scenario(*, scenario_key, **kwargs):
        if scenario_key == _FAILING_SCENARIO_KEY:
            failed_calls.append(scenario_key)
            raise OSError("simulated disk-full failure while saving render assets")
        return original_persist(scenario_key=scenario_key, **kwargs)

    monkeypatch.setattr(
        report_pipeline_module,
        "_persist_scenario_render_assets",
        _persist_failing_for_one_scenario,
    )

    with pytest.warns(UserWarning, match="persistir los activos de render"):
        run_dir = prepare(
            _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
        )

    assert failed_calls == [_FAILING_SCENARIO_KEY], "expected the forced failure to actually fire"

    # (b) prepare() completed and produced the three JSON artifacts -- no
    # crash, no orphan run_dir missing them.
    assert (run_dir / "historical.bc.json").exists()
    assert (run_dir / "inference.bc.json").exists()
    assert (run_dir / "l1_state.json").exists()

    # (a) the scenario whose PERSISTENCE failed is still present in
    # `escenarios` with real interpretation/context data -- its SHAP
    # computation succeeded, only the render-asset save failed.
    inference_context = _read_json(run_dir / "inference.bc.json")
    nombres = {escenario["nombre"] for escenario in inference_context["escenarios"]}
    frecuencia_periodo_nombres = [
        nombre for nombre in nombres if "frecuencia" in nombre and "período completo" in nombre
    ]
    assert frecuencia_periodo_nombres, "expected the scenario to survive despite the persistence failure"
    assert len(inference_context["escenarios"]) >= 3, (
        "expected the other scenarios' render assets to be unaffected by one scenario's "
        "persistence failure"
    )

    # (d) the failed scenario has no render_assets entry (its sidecar entry
    # is simply absent, the same shape `render()` already tolerates), while
    # the other scenarios' render assets are unaffected.
    sidecar_path = run_dir / "inference_render_assets.json"
    assert sidecar_path.exists()
    render_assets = _read_json(sidecar_path)
    assert _FAILING_SCENARIO_KEY not in render_assets
    assert len(render_assets) == len(inference_context["escenarios"]) - 1


def test_reporte_end_to_end_with_real_simulator_renders_non_empty_inference_section(
    tmp_path, monkeypatch
):
    """Task 4.2: full prepare -> prepare_expert_alignment -> render with the
    real simulator and a canned (schema+guardrail validated) inference
    output -- the final HTML's inference section must be non-empty (actual
    persisted figures embedded, not the old `None` short-circuit)."""
    _enable_real_mgcecdl_model(monkeypatch)

    run_dir = prepare(
        _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
    )
    (run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico."]})), encoding="utf-8"
    )
    (run_dir / "inference.out.json").write_text(
        json.dumps(_canned_inference_ok(run_dir)), encoding="utf-8"
    )

    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )

    html_path = render(run_dir, output_dir=tmp_path / "html")
    html = html_path.read_text(encoding="utf-8")

    assert html.strip() != ""
    assert "Discusión general de inferencias del modelo" in html
    assert "embedded-figure" in html, "expected a persisted PNG actually embedded in the report"


def test_prepare_regenerates_graph_html_independently_across_consecutive_runs(
    tmp_path, monkeypatch
):
    """Task 4.3: two consecutive prepare() runs for the same circuit/window
    must each independently recompute and write their own HTML graph files
    under their own run_dir -- no caching/reuse by circuit/date-window or any
    other key (spec requirement)."""
    _enable_real_mgcecdl_model(monkeypatch)
    runs_root = tmp_path / "runs"

    run_dir_1 = prepare(_REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=runs_root)
    run_dir_2 = prepare(_REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=runs_root)

    assert run_dir_1 != run_dir_2, "each prepare() call must get its own fresh run_dir"

    graphs_1 = sorted((run_dir_1 / "inference_graphs").glob("*.html"))
    graphs_2 = sorted((run_dir_2 / "inference_graphs").glob("*.html"))
    assert graphs_1, "expected the first run to persist its own HTML graphs"
    assert graphs_2, "expected the second run to persist its own HTML graphs"
    assert len(graphs_1) == len(graphs_2)

    # Independently-written files under distinct run_dirs, not a shared/
    # reused path -- the two runs never touch each other's artifacts.
    names_1 = {path.name for path in graphs_1}
    names_2 = {path.name for path in graphs_2}
    assert names_1 == names_2
    for path_1, path_2 in zip(graphs_1, graphs_2):
        assert path_1.resolve() != path_2.resolve()
        assert path_1.read_bytes(), "first run's HTML must be a real, non-empty file"
        assert path_2.read_bytes(), "second run's HTML must be a real, non-empty file"


def test_prepare_survives_graph_output_dir_creation_failure_whole_run_completes(
    tmp_path, monkeypatch
):
    """`graph_dir.mkdir(...)` failing (permission-denied/disk-full/read-only
    mount) must degrade the WHOLE simulator call for this run -- no scenario
    can persist a graph HTML without a writable directory -- rather than
    crash `prepare()`. The report must still generate all three JSON
    artifacts, with a clear, distinct warning, and no
    `inference_render_assets.json` sidecar."""
    _enable_real_mgcecdl_model(monkeypatch)

    original_mkdir = Path.mkdir

    def _mkdir_failing_for_graph_dir(self, *args, **kwargs):
        if self.name == "inference_graphs":
            raise OSError("simulated permission-denied creating graph output dir")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _mkdir_failing_for_graph_dir)

    with pytest.warns(UserWarning, match="directorio de salida de grafos"):
        run_dir = prepare(
            _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
        )

    assert (run_dir / "historical.bc.json").exists()
    assert (run_dir / "inference.bc.json").exists()
    assert (run_dir / "l1_state.json").exists()

    inference_context = _read_json(run_dir / "inference.bc.json")
    assert inference_context["escenarios"] == []
    assert inference_context["features"], (
        "expected features to stay populated -- this is the whole-call "
        "degrade shape, distinct from the R3 'no trained model' gap"
    )
    assert not (run_dir / "inference_render_assets.json").exists()


def test_prepare_survives_render_assets_sidecar_write_failure_keeps_run_completes(
    tmp_path, monkeypatch
):
    """An `OSError` raised specifically while writing the top-level
    `inference_render_assets.json` sidecar (Round 3 gap: this
    `save_json_artifact` call, unlike the ones just above/below it, was
    unguarded) must NOT crash `prepare()` -- `_run_inference_simulator`
    already succeeded by this point (features/escenarios computed, PNGs/HTML
    already on disk), so a transient fault at just this line must degrade to
    "no sidecar for this run" (the same shape `_build_inference_results`
    already tolerates for an absent sidecar), not abort an otherwise fully
    successful run."""
    _enable_real_mgcecdl_model(monkeypatch)

    original_save_json_artifact = report_pipeline_module.save_json_artifact

    def _save_json_artifact_failing_for_sidecar(payload, path):
        if Path(path).name == "inference_render_assets.json":
            raise OSError("simulated disk-full failure writing render-assets sidecar")
        return original_save_json_artifact(payload, path)

    monkeypatch.setattr(
        report_pipeline_module, "save_json_artifact", _save_json_artifact_failing_for_sidecar
    )

    with pytest.warns(UserWarning, match="sidecar de activos de render"):
        run_dir = prepare(
            _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
        )

    # (a) prepare() completed without crashing.
    # (b) historical.bc.json/inference.bc.json/l1_state.json are all still
    # written -- none of them is skipped just because the sidecar write
    # failed.
    assert (run_dir / "historical.bc.json").exists()
    assert (run_dir / "inference.bc.json").exists()
    assert (run_dir / "l1_state.json").exists()

    # (c) inference.bc.json's escenarios/features are unaffected -- they were
    # already computed by `_run_inference_simulator` before this write, which
    # only persists a sidecar derived from that already-successful result.
    inference_context = _read_json(run_dir / "inference.bc.json")
    assert inference_context["features"], "expected features to stay populated"
    assert len(inference_context["escenarios"]) >= 1, "expected escenarios to stay populated"

    # (d) no inference_render_assets.json file exists.
    assert not (run_dir / "inference_render_assets.json").exists()


def test_prepare_survives_graph_html_write_failure_for_one_scenario_keeps_others_and_completes(
    tmp_path, monkeypatch
):
    """An `OSError`/`PermissionError` raised while writing ONE scenario's
    interactive graph HTML (inside `graficar_barras_y_radar` ->
    `mostrar_grafo_interactivo_muestras`) must degrade only THAT scenario --
    it is omitted from `escenarios` with a distinct warning -- without
    crashing `prepare()` and without affecting the other scenarios computed
    in the same run."""
    _enable_real_mgcecdl_model(monkeypatch)

    import chec_impacto.interpretability.circuit_analysis as circuit_analysis_module

    original_mostrar = circuit_analysis_module.mostrar_grafo_interactivo_muestras
    _FAILING_GRAPH_NAME = "top_frecuencia_periodo.html"
    failed_calls: list[str] = []

    def _mostrar_failing_for_one_scenario(*args, **kwargs):
        output_path = kwargs.get("output_path")
        if output_path is not None and Path(output_path).name == _FAILING_GRAPH_NAME:
            failed_calls.append(_FAILING_GRAPH_NAME)
            raise OSError("simulated permission-denied writing graph HTML")
        return original_mostrar(*args, **kwargs)

    monkeypatch.setattr(
        circuit_analysis_module,
        "mostrar_grafo_interactivo_muestras",
        _mostrar_failing_for_one_scenario,
    )

    with pytest.warns(UserWarning, match="no se pudo escribir el grafo HTML"):
        run_dir = prepare(
            _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
        )

    assert failed_calls == [_FAILING_GRAPH_NAME], "expected the forced failure to actually fire"

    assert (run_dir / "historical.bc.json").exists()
    assert (run_dir / "inference.bc.json").exists()
    assert (run_dir / "l1_state.json").exists()

    inference_context = _read_json(run_dir / "inference.bc.json")
    nombres = {escenario["nombre"] for escenario in inference_context["escenarios"]}
    frecuencia_periodo_nombres = [
        nombre for nombre in nombres if "frecuencia" in nombre and "período completo" in nombre
    ]
    assert not frecuencia_periodo_nombres, "expected the failing scenario to be omitted entirely"
    assert len(inference_context["escenarios"]) >= 3, (
        "expected the other scenarios to be unaffected by one scenario's graph-HTML write failure"
    )


# ---------------------------------------------------------------------------
# `_run_automatic_simulator` (agent-native-pipeline-and-site-split PR A1,
# tasks 1.2/1.3, design D2): standalone unit tests for the automatic min/max
# sensitivity simulator orchestration. `model=None` degrade needs no real
# data (returns before touching the dataset); the happy path needs the REAL
# committed model + a real circuit/window, same precedent as the "real
# inference simulator" section above.
# ---------------------------------------------------------------------------


def test_run_automatic_simulator_degrades_to_none_when_model_is_none(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = report_pipeline_module._run_automatic_simulator(
        "ANY-CIRCUIT", "2026-01-01", "2026-01-01", [], run_dir, None
    )

    assert result is None
    assert not (run_dir / "auto-simulator.bc.json").exists()
    assert not (run_dir / "auto_simulation_assets.json").exists()


def test_run_automatic_simulator_zero_events_in_window_degrades_to_none(tmp_path, monkeypatch):
    """Mirrors the inference simulator's own zero-events degrade: a real
    model but a circuit/window with no matching rows returns `None` without
    writing any artifact, rather than raising inside `simulate_automatic_
    minmax_sensitivity` (which requires a non-empty mask)."""
    _enable_real_mgcecdl_model(monkeypatch)
    model, _rbf_sigma = report_pipeline_module._load_mgcecdl_model_and_sigma()
    assert model is not None
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = report_pipeline_module._run_automatic_simulator(
        _REAL_SUFFICIENT_CIRCUIT, "2020-01-01", "2020-01-02", [], run_dir, model
    )

    assert result is None
    assert not (run_dir / "auto-simulator.bc.json").exists()
    assert not (run_dir / "auto_simulation_assets.json").exists()


def test_run_automatic_simulator_happy_path_writes_bc_and_assets(tmp_path, monkeypatch):
    _enable_real_mgcecdl_model(monkeypatch)
    run_dir = prepare(
        _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
    )
    inference_context = _read_json(run_dir / "inference.bc.json")
    assert inference_context["escenarios"], (
        "expected at least one real scenario with top_variables to drive a "
        "non-trivial automatic-simulator happy path"
    )

    model, _rbf_sigma = report_pipeline_module._load_mgcecdl_model_and_sigma()
    assert model is not None

    result = report_pipeline_module._run_automatic_simulator(
        _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, [], run_dir, model
    )

    assert result is not None
    bc_path = run_dir / "auto-simulator.bc.json"
    assets_path = run_dir / "auto_simulation_assets.json"
    assert bc_path.exists()
    assert assets_path.exists()

    bc = _read_json(bc_path)
    assert bc["contexto"]["circuito"] == _REAL_SUFFICIENT_CIRCUIT
    assert bc["contexto"]["modelo"] == type(model).__name__
    assert bc["tabla_simulador_automatico"], "expected at least one simulated variable row"
    assert bc["variables_bajo_analisis"], "expected variables re-derived from inference.bc.json"
    assert bc["contexto_inferencia_resumen"]["escenarios"]

    assets = _read_json(assets_path)
    assert assets["table"], "expected the sidecar's table records to be non-empty"
    assert "cost_context" in assets
    assert "softmax_curves" in assets
    assert "vano_risk" in assets


# ---------------------------------------------------------------------------
# `prepare()` wiring of the automatic simulator (task 1.3): with the default
# (autoused) empty model dir, `prepare()` must degrade exactly like it
# already does for the inference simulator (no artifacts, no crash). With
# the real model, it must produce the auto-simulator artifacts as a side
# effect of a single `prepare()` call.
# ---------------------------------------------------------------------------


def test_prepare_does_not_write_auto_simulator_artifacts_when_model_missing(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)

    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")

    assert not (run_dir / "auto-simulator.bc.json").exists()
    assert not (run_dir / "auto_simulation_assets.json").exists()


def test_prepare_writes_auto_simulator_artifacts_with_real_model(tmp_path, monkeypatch):
    _enable_real_mgcecdl_model(monkeypatch)

    run_dir = prepare(
        _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
    )

    assert (run_dir / "auto-simulator.bc.json").exists()
    assert (run_dir / "auto_simulation_assets.json").exists()


# ---------------------------------------------------------------------------
# `render()` / `_build_auto_simulation_kwargs` (task 1.4): absent auto-
# simulator artifacts keep every `automatic_simulation_*` kwarg `None`
# (no crash); present artifacts populate all 5 kwargs from the sidecar +
# validated agent-output envelope.
# ---------------------------------------------------------------------------


def test_render_auto_simulation_kwargs_absent_stays_none_no_crash(tmp_path, monkeypatch):
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    assert not (run_dir / "auto_simulation_assets.json").exists()
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["H1"]})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["I1"]})), encoding="utf-8")
    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        for key in (
            "automatic_simulation_table",
            "automatic_simulation_analysis",
            "automatic_simulation_cost_context",
            "automatic_simulation_softmax_curves",
            "automatic_simulation_vano_risk_df",
        ):
            captured[key] = kwargs.get(key)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html")

    assert captured["automatic_simulation_table"] is None
    assert captured["automatic_simulation_analysis"] is None
    assert captured["automatic_simulation_cost_context"] is None
    assert captured["automatic_simulation_softmax_curves"] is None
    assert captured["automatic_simulation_vano_risk_df"] is None


def test_render_auto_simulation_kwargs_present_populates_all_five(tmp_path, monkeypatch):
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["H1"]})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["I1"]})), encoding="utf-8")
    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )

    (run_dir / "auto_simulation_assets.json").write_text(
        json.dumps(
            {
                "table": [{"variable": "CNT_TRF", "magnitud_max_cambio_abs": 0.1}],
                "vano_risk": [{"FID_VANO": "V0", "delta_riesgo_ordinal": 0.2}],
                "cost_context": {"disponible": True, "coincidencias": []},
                "softmax_curves": {"variables": [], "metadata": {"warnings": []}},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "auto-simulator.out.json").write_text(
        json.dumps(_canned_ok({"titulo": "Discusión automática", "resumen": ["R1"]})), encoding="utf-8"
    )

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        for key in (
            "automatic_simulation_table",
            "automatic_simulation_analysis",
            "automatic_simulation_cost_context",
            "automatic_simulation_softmax_curves",
            "automatic_simulation_vano_risk_df",
        ):
            captured[key] = kwargs.get(key)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html")

    assert captured["automatic_simulation_table"] is not None
    assert list(captured["automatic_simulation_table"]["variable"]) == ["CNT_TRF"]
    assert captured["automatic_simulation_analysis"] == {"titulo": "Discusión automática", "resumen": ["R1"]}
    assert captured["automatic_simulation_cost_context"] == {"disponible": True, "coincidencias": []}
    assert captured["automatic_simulation_softmax_curves"] == {"variables": [], "metadata": {"warnings": []}}
    assert captured["automatic_simulation_vano_risk_df"] is not None
    assert list(captured["automatic_simulation_vano_risk_df"]["FID_VANO"]) == ["V0"]


# ---------------------------------------------------------------------------
# Coverage-proof gate (task 1.7): a full, real `/reporte` run -- prepare()
# with the REAL committed model (writing real auto-simulator artifacts as a
# side effect) through render() -- with no LLM API key set anywhere in the
# process, must actually embed the automatic-simulation discussion section
# in the final HTML. This is the scenario the spec's "Deletion of 02/
# llm_client.py permitted after /reporte coverage proven" requirement gates
# notebook 02's deletion on.
# ---------------------------------------------------------------------------


def test_reporte_end_to_end_with_real_simulator_renders_auto_simulation_section(
    tmp_path, monkeypatch
):
    for env_var in ("GOOGLE_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(env_var, raising=False)
    _enable_real_mgcecdl_model(monkeypatch)

    run_dir = prepare(
        _REAL_SUFFICIENT_CIRCUIT, *_REAL_SUFFICIENT_WINDOW, runs_root=tmp_path / "runs"
    )
    # prepare() already ran the real automatic simulator as a side effect
    # (no LLM call anywhere in report_pipeline.py) -- this is the same
    # coverage this file's other real-simulator tests confirm for the
    # inference/SHAP simulator, now extended to the automatic one.
    assert (run_dir / "auto-simulator.bc.json").exists()
    assert (run_dir / "auto_simulation_assets.json").exists()

    (run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico."]})), encoding="utf-8"
    )
    (run_dir / "inference.out.json").write_text(
        json.dumps(_canned_inference_ok(run_dir)), encoding="utf-8"
    )
    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )
    # No auto-simulator.out.json is written here: the auto-simulator agent
    # step is optional/degrade-to-skip (SKILL.md step 4b) -- the coverage
    # proof only requires the automatic-simulation TABLE to render, which
    # `prepare()`'s real run already persisted via the sidecar.

    html_path = render(run_dir, output_dir=tmp_path / "html")
    html = html_path.read_text(encoding="utf-8")

    assert html.strip() != ""
    # `render_expert_alignment_tab`'s `_post_prioritization_simulator_visuals()`
    # is the code path actually wired into the final HTML template (unlike the
    # sibling `_auto_simulation_section()` helper in plotting.py, which builds
    # a similarly-named section but is never called from anywhere) -- this is
    # the real, rendered proof that the automatic simulator's table reached
    # the report.
    assert "Gráficas del simulador automático" in html, (
        "expected the automatic min/max sensitivity visuals section to actually "
        "render, proving /reporte covers what notebook 02 used to produce"
    )
