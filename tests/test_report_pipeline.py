from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import chec_local_interpreter.report_pipeline as report_pipeline_module
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
