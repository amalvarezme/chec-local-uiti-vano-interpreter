from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import chec_local_interpreter.report_pipeline as report_pipeline_module
from chec_local_interpreter.config import DEFAULT_MODEL_DIR as _REAL_DEFAULT_MODEL_DIR
from chec_local_interpreter.inference_validation import validar_respuesta_inferencia_strict
from chec_local_interpreter.report_pipeline import (
    ReportPipelineError,
    preflight,
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


_MULTI_MONTH_SPIKE_DAYS = (
    "2026-01-15",
    "2026-02-15",
    "2026-03-15",
    "2026-04-15",
    "2026-05-15",
    "2026-06-15",
    "2026-07-15",
)


def _write_multi_month_fixture_dataset(directory: Path) -> Path:
    """Circuit C1 spanning 7 distinct calendar months (2026-01-01..2026-07-31)
    with one clear spike day per month (`_MULTI_MONTH_SPIKE_DAYS`, value 60.0
    against a flat 4.0 baseline) -- enough qualifying critical-point
    candidates that the month-scaled budget (7, within [5, 12]) is the
    binding constraint, not the number of detected candidates."""
    dates = pd.date_range("2026-01-01", "2026-07-31", freq="D")
    rows = []
    for date in dates:
        fecha_text = date.strftime("%Y-%m-%d")
        rows.append(
            {
                "CIRCUITO": "C1",
                "FECHA": fecha_text,
                "UITI_VANO": 60.0 if fecha_text in _MULTI_MONTH_SPIKE_DAYS else 4.0,
                "FID_VANO": f"V{fecha_text}",
                "DESC_CAUSA": "Viento",
            }
        )
    frame = pd.DataFrame(rows)
    csv_path = directory / "dataset_multi_month.csv"
    frame.to_csv(csv_path, index=False)
    return csv_path


def _canned_ok(data: dict) -> dict:
    return {"ok": True, "data": data}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# preflight()
# ---------------------------------------------------------------------------


def test_preflight_resolves_default_window_without_creating_run_dir(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    runs_root = tmp_path / "runs"

    result = preflight("C1", data_path=data_path)

    assert result.circuito == "C1"
    assert result.fecha_inicio == "2026-01-01"
    assert result.fecha_fin == "2026-01-10"
    assert result.event_count == 10
    assert not runs_root.exists()


def test_preflight_rejects_lone_date_before_run_dir(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)
    runs_root = tmp_path / "runs"

    with pytest.raises(ReportPipelineError, match="pair"):
        preflight("C1", "2026-01-01", data_path=data_path)

    assert not runs_root.exists()


def test_preflight_matches_prepare_resolved_window(tmp_path):
    data_path = _write_fixture_dataset(tmp_path)

    resolved = preflight("C1", data_path=data_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    state = _read_json(run_dir / "l1_state.json")

    assert state["fecha_inicio"] == resolved.fecha_inicio
    assert state["fecha_fin"] == resolved.fecha_fin


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
    # `ventanas_estudio` sustituye a `critical_points`: sin artefacto del MIL (la fixture
    # autouse apunta a un directorio de modelo vacio) la seleccion queda vacia, que es la
    # forma correcta del hueco -- no hay modelo con el que elegir ventanas.
    assert state["ventanas_estudio"] == []
    assert "critical_points" not in state

    historical_context = _read_json(run_dir / "historical.bc.json")
    # graph_knowledge is retired at the source (informe-gerencial-graph-noise-
    # cleanup, Prong B): `build_context_package` never invokes
    # `graph_extractor.build_graphify_context`/any graphify subprocess/PyVis
    # fallback, so the persisted context artifact must never carry the key.
    assert "graph_knowledge" not in historical_context

    inference_context = _read_json(run_dir / "inference.bc.json")
    assert inference_context["circuito_interes"] == "C1"
    assert inference_context["fecha_inicio"] == "2026-01-01"
    assert inference_context["fecha_fin"] == "2026-01-10"


def test_prepare_builds_the_window_grid_from_the_full_range_not_the_slice(tmp_path):
    """Las etiquetas `V1`..`Vn` las fija el rango COMPLETO de la base, no el recorte del
    informe: es la misma rejilla con la que el cuaderno 05 construyo el cache de bolsas.
    Derivarlas del subconjunto filtrado hacia que la `V1` del historiador y la `V1` del
    modelo fueran dos periodos distintos con el mismo nombre."""
    data_path = _write_multi_month_fixture_dataset(tmp_path)

    run_dir = prepare(
        "C1", "2026-01-01", "2026-03-31", data_path=data_path, runs_root=tmp_path / "runs"
    )

    ventanas = _read_json(run_dir / "historical.bc.json")["ventanas"]
    # La base cubre enero..julio, asi que la rejilla tiene mas ventanas que el recorte.
    assert len(ventanas) > 6
    assert ventanas[0]["desde"] == "2026-01-01"
    # Y las de fuera del recorte estan, en cero: una ventana sin eventos es un dato.
    assert any(v["uv"] == 0.0 for v in ventanas)






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
    # El periodo global del informe confirma que la agrupacion ocurre y no devuelve una
    # lista vacia fija. Las fechas de las ventanas estudiadas entran como
    # `ventana_estudiada` cuando hay modelo; esta fixture apunta a un modelo vacio.
    assert "context" in sources
    assert "critical_point" not in sources


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
# prepare_expert_alignment() -- prior-report reuse wiring (sdd/reporte-graph-
# reuse, PR 2, tasks 4.9/4.10). Discovery (`seleccionar_reporte_previo_mas_reciente`)
# + normalization (`normalizar_reporte_previo_como_matches`) are called after
# `pdf_expert_matches` is built and before `construir_contexto_expert_alignment`.
# ---------------------------------------------------------------------------


def test_prepare_expert_alignment_wires_prior_report_when_qualifying_prior_run_exists(tmp_path):
    runs_root = tmp_path / "runs"

    # Prior run: fully completed (has its OWN valid expert-alignment.out.json).
    data_path = _write_fixture_dataset(tmp_path)
    prior_run_dir = prepare("C1", data_path=data_path, runs_root=runs_root)
    (prior_run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico previo."]})), encoding="utf-8"
    )
    (prior_run_dir / "inference.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo de inferencia previo."]})), encoding="utf-8"
    )
    prepare_expert_alignment(prior_run_dir)
    (prior_run_dir / "expert-alignment.out.json").write_text(
        json.dumps(
            _canned_ok(
                {
                    "contexto": {
                        "circuito": "C1",
                        "periodo": {"inicio": "2026-01-01", "fin": "2026-01-10"},
                        "n_filas_expertas_comparadas": 0,
                    },
                    "coincidencias": [
                        {
                            "tema": "UITI_VANO elevado en el periodo previo",
                            "fuentes": ["Agente Descriptor", "Agente predictivo"],
                            "explicacion": "Consistencia observada en la ejecución previa.",
                        }
                    ],
                    "diferencias": [],
                    "hallazgos_expertos_no_cubiertos": [],
                    "hallazgos_modelo_no_respaldados_por_pdf": [],
                    "variables_a_priorizar": [],
                    "sintesis_final": "La comparación previa fue consistente.",
                }
            )
        ),
        encoding="utf-8",
    )

    # Current run: same circuit, new run_dir under the same runs_root, so the
    # prior run above is a qualifying sibling for discovery.
    current_run_dir = prepare("C1", data_path=data_path, runs_root=runs_root)
    (current_run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico actual."]})), encoding="utf-8"
    )
    (current_run_dir / "inference.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo de inferencia actual."]})), encoding="utf-8"
    )

    prepare_expert_alignment(current_run_dir)

    bc = _read_json(current_run_dir / "expert-alignment.bc.json")
    prior_rows = [row for row in bc["pdf_expert_matches"] if row.get("source_kind") == "prior_report"]
    assert prior_rows, "expected at least one prior-report row wired into pdf_expert_matches"
    assert prior_rows[0]["confidence"] == "baja"
    assert bc.get("reporte_previo_disponible") is True


_GOLDEN_DIR = Path(__file__).parent / "golden" / "reporte_graph_reuse"


def test_prepare_expert_alignment_pdf_only_output_matches_pre_wiring_golden_byte_for_byte(tmp_path):
    """The byte-identical no-op guard: `expert-alignment.bc.json` for a PDF-only fixture
    (real PDF matches, no prior run) must match a committed golden BYTE FOR BYTE.

    What it locks is the PRIOR-REPORT no-op path: a run with no qualifying prior run must
    produce exactly the PDF-only output, with no extra key and no extra match. If this
    test fails, the bug is in that no-op path -- do not update the golden to paper over a
    changed no-op.

    The golden was regenerated ONCE, deliberately, when critical-point detection was
    retired: `fechas_informe` used to carry `critical_point`-sourced records with weight
    3.0, and those dates no longer exist anywhere in the flow. That is a change of input,
    not a regression of the no-op path this test guards."""
    run_dir = _prepare_with_canned_agent_outputs(tmp_path)
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

    prepare_expert_alignment(run_dir, pdf_discussions_path=xlsx_path)

    actual = (run_dir / "expert-alignment.bc.json").read_text(encoding="utf-8")
    golden = (_GOLDEN_DIR / "expert_alignment_pdf_only_bc.json").read_text(encoding="utf-8")
    assert actual == golden


def test_prepare_expert_alignment_no_qualifying_prior_run_is_a_pure_no_op(tmp_path):
    """Task 4.11/4.12: with no sibling prior run for the circuit (the common
    case -- first run ever, or every prior run incomplete), wiring
    discovery+normalization into `prepare_expert_alignment` must leave the
    context byte-identical to the pre-wiring shape: no `reporte_previo_disponible`
    key, and no `source_kind: "prior_report"` rows in `pdf_expert_matches`."""
    run_dir = _prepare_with_canned_agent_outputs(tmp_path)

    prepare_expert_alignment(run_dir)

    bc = _read_json(run_dir / "expert-alignment.bc.json")
    assert "reporte_previo_disponible" not in bc
    assert all(row.get("source_kind") != "prior_report" for row in bc["pdf_expert_matches"])


def test_prepare_expert_alignment_schema_invalid_prior_output_degrades_to_no_op(tmp_path):
    """Judgment Day Round 2 CRITICAL fix: a sibling prior run whose own
    `expert-alignment.out.json` is syntactically valid JSON with a valid
    `{"ok": true, "data": ...}` envelope shape, but `data` itself is a
    non-dict (a realistic partial/buggy write), must be treated as a
    non-qualifying candidate -- `prepare_expert_alignment` for the CURRENT
    run must complete normally with no prior-report evidence wired, never
    crash with `AttributeError`."""
    runs_root = tmp_path / "runs"
    data_path = _write_fixture_dataset(tmp_path)

    prior_run_dir = prepare("C1", data_path=data_path, runs_root=runs_root)
    (prior_run_dir / "expert-alignment.out.json").write_text(
        json.dumps({"ok": True, "data": ["not", "a", "dict"]}), encoding="utf-8"
    )

    current_run_dir = prepare("C1", data_path=data_path, runs_root=runs_root)
    (current_run_dir / "historical.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo historico actual."]})), encoding="utf-8"
    )
    (current_run_dir / "inference.out.json").write_text(
        json.dumps(_canned_ok({"hallazgos": ["Hallazgo de inferencia actual."]})), encoding="utf-8"
    )

    result = prepare_expert_alignment(current_run_dir)

    assert result == current_run_dir
    bc = _read_json(current_run_dir / "expert-alignment.bc.json")
    assert "reporte_previo_disponible" not in bc
    assert all(row.get("source_kind") != "prior_report" for row in bc["pdf_expert_matches"])


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
















# ---------------------------------------------------------------------------
# `_run_automatic_simulator` (agent-native-pipeline-and-site-split PR A1,
# tasks 1.2/1.3, design D2): standalone unit tests for the automatic min/max
# sensitivity simulator orchestration. `model=None` degrade needs no real
# data (returns before touching the dataset); the happy path needs the REAL
# committed model + a real circuit/window, same precedent as the "real
# inference simulator" section above.
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# `prepare()` wiring of the automatic simulator (task 1.3): with the default
# (autoused) empty model dir, `prepare()` must degrade exactly like it
# already does for the inference simulator (no artifacts, no crash). With
# the real model, it must produce the auto-simulator artifacts as a side
# effect of a single `prepare()` call.
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Shared dataset/scaler inputs (SDD `reporte-perf-optimization`, item 3):
# `_compute_inference_scenarios` (via `_run_inference_simulator`) and
# `_run_automatic_simulator` must consume the IDENTICAL `procesar_dataset_
# completo` result and fitted MinMax `feature_scaler` within one `prepare()`
# call, computed exactly once -- not recomputed independently by each
# consumer and merely hoped to match.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# `render()` / `_build_auto_simulation_kwargs` (task 1.4): absent auto-
# simulator artifacts keep every `automatic_simulation_*` kwarg `None`
# (no crash); present artifacts populate all 5 kwargs from the sidecar +
# validated agent-output envelope.
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Coverage-proof gate (task 1.7): a full, real `/reporte` run -- prepare()
# with the REAL committed model (writing real auto-simulator artifacts as a
# side effect) through render() -- with no LLM API key set anywhere in the
# process, must actually embed the automatic-simulation discussion section
# in the final HTML. This is the scenario the spec's "Deletion of 02/
# llm_client.py permitted after /reporte coverage proven" requirement gates
# notebook 02's deletion on.
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Real token usage instrumentation (SDD `reporte-perf-optimization`, item 4):
# `_resolve_token_usage(run_dir) -> (tokens_input, tokens_output, tokens_total, token_source, token_total_source)`
# replaces `_estimate_token_usage`, preferring real per-stage counts from an
# optional `run_dir/token_usage.json` sidecar over the char/4 estimate, and
# labeling the resolved source ("measured"/"mixed"/"estimated"). `render()`'s
# precedence is explicit kwargs > sidecar > estimate; no-arg callers must stay
# unbroken (already covered by the pre-existing render() tests above, none of
# which pass `tokens_input`/`tokens_output`).
# ---------------------------------------------------------------------------


def _write_stage_files(run_dir: Path, stage: str, *, bc_text: str, out_data: dict) -> None:
    (run_dir / f"{stage}.bc.json").write_text(bc_text, encoding="utf-8")
    (run_dir / f"{stage}.out.json").write_text(json.dumps(_canned_ok(out_data)), encoding="utf-8")


def test_resolve_token_usage_no_sidecar_is_estimated_char_based(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    _write_stage_files(run_dir, "inference", bc_text="x" * 120, out_data={"b": "y" * 80})

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    expected_chars_in = 400 + 120
    expected_chars_out = len(json.dumps({"a": "y" * 200})) + len(json.dumps({"b": "y" * 80}))
    assert tokens_input == expected_chars_in // 4
    assert tokens_output == expected_chars_out // 4
    assert tokens_total == tokens_input + tokens_output
    assert token_source == "estimated"


def test_resolve_token_usage_full_sidecar_is_measured_real_counts(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    _write_stage_files(run_dir, "inference", bc_text="x" * 120, out_data={"b": "y" * 80})
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"input": 100, "output": 50}, "inference": {"input": 200, "output": 80}}),
        encoding="utf-8",
    )

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    assert tokens_input == 300
    assert tokens_output == 130
    assert tokens_total == tokens_input + tokens_output
    assert token_source == "measured"


def test_resolve_token_usage_partial_sidecar_is_mixed(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    _write_stage_files(run_dir, "inference", bc_text="x" * 120, out_data={"b": "y" * 80})
    # Sidecar covers ONLY "historical" -- "inference" must fall back to the
    # char/4 estimate for its own stage.
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"input": 100, "output": 50}}), encoding="utf-8"
    )

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    inference_chars_in = 120
    inference_chars_out = len(json.dumps({"b": "y" * 80}))
    assert tokens_input == 100 + inference_chars_in // 4
    assert tokens_output == 50 + inference_chars_out // 4
    assert tokens_total == tokens_input + tokens_output
    assert token_source == "mixed"


def test_resolve_token_usage_no_stage_files_returns_zero_estimated(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    assert (tokens_input, tokens_output, tokens_total, token_source, token_total_source) == (0, 0, 0, "estimated", "estimated")


# ---------------------------------------------------------------------------
# Judgment Day round 1 fix: `_resolve_token_usage` must degrade gracefully
# (never raise) for ANY malformed `run_dir/token_usage.json` sidecar --
# top-level invalid JSON, a considered stage's entry with non-numeric
# "input"/"output" values, or a considered stage's entry that isn't a dict at
# all. Each malformed case must degrade to the char/4 estimate for that/those
# stage(s) only, exactly as if the sidecar were absent for that stage.
# ---------------------------------------------------------------------------


def test_resolve_token_usage_malformed_top_level_json_degrades_to_estimate(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    (run_dir / "token_usage.json").write_text("{not valid json", encoding="utf-8")

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    expected_chars_in = 400
    expected_chars_out = len(json.dumps({"a": "y" * 200}))
    assert tokens_input == expected_chars_in // 4
    assert tokens_output == expected_chars_out // 4
    assert tokens_total == tokens_input + tokens_output
    assert token_source == "estimated"


def test_resolve_token_usage_non_numeric_stage_values_degrade_that_stage_only(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"input": "lots", "output": 5}}), encoding="utf-8"
    )

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    expected_chars_in = 400
    expected_chars_out = len(json.dumps({"a": "y" * 200}))
    assert tokens_input == expected_chars_in // 4
    assert tokens_output == expected_chars_out // 4
    assert tokens_total == tokens_input + tokens_output
    assert token_source == "estimated"


def test_resolve_token_usage_non_dict_stage_entry_degrades_that_stage_only(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": "not-a-dict"}), encoding="utf-8"
    )

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    expected_chars_in = 400
    expected_chars_out = len(json.dumps({"a": "y" * 200}))
    assert tokens_input == expected_chars_in // 4
    assert tokens_output == expected_chars_out // 4
    assert tokens_total == tokens_input + tokens_output
    assert token_source == "estimated"


# ---------------------------------------------------------------------------
# `{"total": int}` sidecar shape -- for stages dispatched as real sub-agents
# via Claude Code's `Agent` tool, whose completion notification only reports
# a single combined `subagent_tokens` figure with no input/output split.
# ---------------------------------------------------------------------------


def test_resolve_token_usage_total_only_shape_counts_as_measured(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"total": 777}}), encoding="utf-8"
    )

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    # tokens_total gets the real sidecar total directly.
    assert tokens_total == 777
    # No split given -- tokens_input/tokens_output individually still fall
    # back to the char/4 estimate for this stage.
    expected_chars_in = 400
    expected_chars_out = len(json.dumps({"a": "y" * 200}))
    assert tokens_input == expected_chars_in // 4
    assert tokens_output == expected_chars_out // 4
    # The total is measured, but the input/output split is still estimated.
    assert token_source == "estimated"
    assert token_total_source == "measured"


def test_resolve_token_usage_mixed_shapes_across_stages(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    _write_stage_files(run_dir, "inference", bc_text="x" * 120, out_data={"b": "y" * 80})
    (run_dir / "token_usage.json").write_text(
        json.dumps(
            {
                "historical": {"input": 100, "output": 50},
                "inference": {"total": 999},
            }
        ),
        encoding="utf-8",
    )

    tokens_input, tokens_output, tokens_total, token_source, token_total_source = report_pipeline_module._resolve_token_usage(run_dir)

    # The total is measured for both stages, but the input/output split is
    # measured for only one stage.
    assert token_source == "mixed"
    assert token_total_source == "measured"
    assert tokens_total == (100 + 50) + 999
    # historical's split contributes directly; inference's total-only shape
    # falls back to the char/4 estimate for its own input/output split.
    inference_chars_in = 120
    inference_chars_out = len(json.dumps({"b": "y" * 80}))
    assert tokens_input == 100 + inference_chars_in // 4
    assert tokens_output == 50 + inference_chars_out // 4


# ---------------------------------------------------------------------------
# `_resolve_elapsed_seconds(run_dir) -> float | None` -- total wall-clock
# execution time, resolved from `run_dir.name`'s own UTC timestamp (written
# by `_new_run_dir` as `%Y%m%dT%H%M%S%f`), degrading to `None` (never
# raising) when the folder name doesn't match that format.
# ---------------------------------------------------------------------------


def test_resolve_elapsed_seconds_valid_timestamp_returns_positive_float(tmp_path):
    from datetime import datetime, timedelta, timezone

    started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    run_dir = tmp_path / started_at.strftime("%Y%m%dT%H%M%S%f")
    run_dir.mkdir()

    real_now = datetime.now(timezone.utc)
    elapsed = report_pipeline_module._resolve_elapsed_seconds(run_dir)

    assert elapsed is not None
    assert elapsed > 0
    assert elapsed < (real_now - started_at).total_seconds() + 5


def test_resolve_elapsed_seconds_invalid_format_returns_none(tmp_path):
    run_dir = tmp_path / "not-a-timestamp"
    run_dir.mkdir()

    assert report_pipeline_module._resolve_elapsed_seconds(run_dir) is None


def _prepare_render_ready_run_dir(tmp_path: Path) -> Path:
    data_path = _write_fixture_dataset(tmp_path)
    run_dir = prepare("C1", data_path=data_path, runs_root=tmp_path / "runs")
    (run_dir / "historical.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["H1"]})), encoding="utf-8")
    (run_dir / "inference.out.json").write_text(json.dumps(_canned_ok({"hallazgos": ["I1"]})), encoding="utf-8")
    prepare_expert_alignment(run_dir)
    (run_dir / "expert-alignment.out.json").write_text(
        json.dumps(_canned_ok({"sintesis_final": "Todo alineado."})), encoding="utf-8"
    )
    return run_dir


def test_render_precedence_explicit_kwargs_beat_sidecar_and_estimate(tmp_path, monkeypatch):
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"input": 1, "output": 1}, "inference": {"input": 1, "output": 1}}),
        encoding="utf-8",
    )

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured.update(kwargs)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html", tokens_input=999, tokens_output=888)

    assert captured["tokens_input"] == 999
    assert captured["tokens_output"] == 888
    assert captured["token_source"] == "measured"


def test_render_precedence_explicit_tokens_total_and_elapsed_seconds_win(tmp_path, monkeypatch):
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"total": 1}, "inference": {"total": 1}}),
        encoding="utf-8",
    )

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured.update(kwargs)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html", tokens_total=123456, elapsed_seconds=42.5)

    assert captured["tokens_total"] == 123456
    assert captured["elapsed_seconds"] == 42.5


def test_render_uses_sidecar_when_no_explicit_kwargs(tmp_path, monkeypatch):
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    (run_dir / "token_usage.json").write_text(
        json.dumps(
            {
                "historical": {"input": 111, "output": 22},
                "inference": {"input": 333, "output": 44},
                "expert-alignment": {"input": 55, "output": 6},
            }
        ),
        encoding="utf-8",
    )

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured.update(kwargs)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html")

    assert captured["tokens_input"] == 111 + 333 + 55
    assert captured["tokens_output"] == 22 + 44 + 6
    assert captured["token_source"] == "measured"
    assert captured["tokens_total"] == captured["tokens_input"] + captured["tokens_output"]
    assert isinstance(captured["elapsed_seconds"], float)


def test_render_falls_back_to_estimated_when_no_sidecar_no_kwargs(tmp_path, monkeypatch):
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    assert not (run_dir / "token_usage.json").exists()

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured.update(kwargs)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html")

    assert isinstance(captured["tokens_input"], int)
    assert isinstance(captured["tokens_output"], int)
    assert captured["token_source"] == "estimated"
    assert captured["tokens_total"] is None
    assert captured["token_total_source"] == "estimated"
    assert isinstance(captured["elapsed_seconds"], float)


def test_render_partial_kwargs_explicit_side_never_mislabeled_estimated(tmp_path, monkeypatch):
    """Judgment Day round 1 fix: supplying exactly one of `tokens_input`/
    `tokens_output` explicitly is itself a precise/authoritative count for
    that side -- it must never end up mislabeled "estimated" in the combined
    `token_source`, even though the other (omitted) side falls back to
    `_resolve_token_usage`'s char/4 estimate (no sidecar present here)."""
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    assert not (run_dir / "token_usage.json").exists()

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured.update(kwargs)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html", tokens_input=500, tokens_output=None)

    assert captured["tokens_input"] == 500
    assert isinstance(captured["tokens_output"], int)
    assert captured["token_source"] != "estimated", (
        "an explicitly-provided precise tokens_input must never be mislabeled as estimated"
    )


def test_render_reuses_same_html_path_when_metadata_is_enriched_for_same_run(tmp_path, monkeypatch):
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    output_dir = tmp_path / "html"

    def _spy_render_llm_analysis(*args, **kwargs):
        html_path = Path(kwargs["output_dir"]) / kwargs["output_filename"]
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(
            f"Modelo LLM: {kwargs.get('llm_provider')} ({kwargs.get('llm_model')})",
            encoding="utf-8",
        )
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    first_path = render(run_dir, output_dir=output_dir)
    second_path = render(run_dir, output_dir=output_dir, llm_provider="Claude Code", llm_model="claude-sonnet-5")

    assert second_path == first_path
    assert sorted(output_dir.glob("*.html")) == [second_path]
    assert "Claude Code (claude-sonnet-5)" in second_path.read_text(encoding="utf-8")


def test_render_uses_distinct_html_paths_for_distinct_run_dirs(tmp_path, monkeypatch):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_run_dir = _prepare_render_ready_run_dir(first_root)
    second_run_dir = _prepare_render_ready_run_dir(second_root)
    output_dir = tmp_path / "html"

    def _spy_render_llm_analysis(*args, **kwargs):
        html_path = Path(kwargs["output_dir"]) / kwargs["output_filename"]
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    first_path = render(first_run_dir, output_dir=output_dir)
    second_path = render(second_run_dir, output_dir=output_dir)

    assert first_path != second_path
    assert len(list(output_dir.glob("*.html"))) == 2


# ---------------------------------------------------------------------------
# `_resolve_stage_timing(run_dir) -> dict[str, float | None]` -- per-stage
# wall-clock duration read from the optional `run_dir/stage_timing.json`
# sidecar (design ADR-1/ADR-3, PR2). Degrades exactly like
# `_resolve_token_usage`'s sidecar handling: absent/malformed top-level JSON
# -> every stage `None`; a stage whose stored value is negative/non-numeric
# degrades to `None` for THAT stage only. Never raises.
# ---------------------------------------------------------------------------


def test_resolve_stage_timing_no_sidecar_returns_all_none(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = report_pipeline_module._resolve_stage_timing(run_dir)

    assert result == {stage: None for stage in report_pipeline_module.TOKEN_USAGE_STAGES}


def test_resolve_stage_timing_malformed_top_level_json_returns_all_none(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stage_timing.json").write_text("{not valid json", encoding="utf-8")

    result = report_pipeline_module._resolve_stage_timing(run_dir)

    assert result == {stage: None for stage in report_pipeline_module.TOKEN_USAGE_STAGES}






def test_resolve_stage_timing_non_dict_stage_entry_degrades_that_stage_only(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stage_timing.json").write_text(
        json.dumps({"historical": "not-a-dict", "inference": {"duration_seconds": 3.0}}),
        encoding="utf-8",
    )

    result = report_pipeline_module._resolve_stage_timing(run_dir)

    assert result["historical"] is None
    assert result["inference"] == 3.0


# ---------------------------------------------------------------------------
# `_resolve_stage_breakdown(run_dir) -> list[dict]` -- additive-only, per
# design's explicit "resolver decision": duplicates ONLY `_resolve_token_usage`'s
# minimal considered-stage gate + char/4 estimate math, does NOT call or
# modify `_resolve_token_usage`. Each considered stage yields
# `{stage, tokens_total, token_source, duration_seconds, duration_source}`;
# an absent stage (no `.bc.json`/ok `.out.json`) is omitted entirely, never
# errored. Duration is measured-or-absent, never estimated.
# ---------------------------------------------------------------------------


def test_resolve_stage_breakdown_all_stages_measured_tokens_and_duration(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    _write_stage_files(run_dir, "inference", bc_text="x" * 120, out_data={"b": "y" * 80})
    (run_dir / "token_usage.json").write_text(
        json.dumps(
            {
                "historical": {"input": 100, "output": 50},
                "inference": {"total": 999},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "stage_timing.json").write_text(
        json.dumps(
            {
                "historical": {"duration_seconds": 77.4},
                "inference": {"duration_seconds": 123.1},
            }
        ),
        encoding="utf-8",
    )

    breakdown = report_pipeline_module._resolve_stage_breakdown(run_dir)
    by_stage = {entry["stage"]: entry for entry in breakdown}

    assert by_stage["historical"]["tokens_total"] == 150
    assert by_stage["historical"]["token_source"] == "measured"
    assert by_stage["historical"]["duration_seconds"] == 77.4
    assert by_stage["historical"]["duration_source"] == "measured"

    assert by_stage["inference"]["tokens_total"] == 999
    assert by_stage["inference"]["token_source"] == "measured"
    assert by_stage["inference"]["duration_seconds"] == 123.1
    assert by_stage["inference"]["duration_source"] == "measured"


def test_resolve_stage_breakdown_stage_missing_from_token_sidecar_falls_back_to_char4_estimate(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    # No token_usage.json at all -- historical must degrade to the char/4
    # estimate, exactly like `_resolve_token_usage`'s own degrade.

    breakdown = report_pipeline_module._resolve_stage_breakdown(run_dir)
    by_stage = {entry["stage"]: entry for entry in breakdown}

    expected_chars_in = 400
    expected_chars_out = len(json.dumps({"a": "y" * 200}))
    assert by_stage["historical"]["tokens_total"] == expected_chars_in // 4 + expected_chars_out // 4
    assert by_stage["historical"]["token_source"] == "estimated"


def test_resolve_stage_breakdown_stage_missing_stage_timing_duration_is_absent_not_estimated(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_stage_files(run_dir, "historical", bc_text="x" * 400, out_data={"a": "y" * 200})
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"input": 10, "output": 5}}), encoding="utf-8"
    )
    # No stage_timing.json -- duration must be None/absent, never estimated.

    breakdown = report_pipeline_module._resolve_stage_breakdown(run_dir)
    by_stage = {entry["stage"]: entry for entry in breakdown}

    assert by_stage["historical"]["duration_seconds"] is None
    assert by_stage["historical"]["duration_source"] is None
    assert by_stage["historical"]["tokens_total"] == 15




def test_resolve_stage_breakdown_no_stage_files_returns_empty_list(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    assert report_pipeline_module._resolve_stage_breakdown(run_dir) == []


# ---------------------------------------------------------------------------
# `render()` wiring (PR2): passes `stage_breakdown=_resolve_stage_breakdown(run_dir)`
# into `render_llm_analysis`'s kwargs, additive-only (default `None` there).
# ---------------------------------------------------------------------------


def test_render_passes_stage_breakdown_kwarg_to_render_llm_analysis(tmp_path, monkeypatch):
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"total": 111}}), encoding="utf-8"
    )
    (run_dir / "stage_timing.json").write_text(
        json.dumps({"historical": {"duration_seconds": 5.5}}), encoding="utf-8"
    )

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured.update(kwargs)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    render(run_dir, output_dir=tmp_path / "html")

    assert "stage_breakdown" in captured
    by_stage = {entry["stage"]: entry for entry in captured["stage_breakdown"]}
    assert by_stage["historical"]["tokens_total"] == 111
    assert by_stage["historical"]["duration_seconds"] == 5.5


# ---------------------------------------------------------------------------
# Regression locks (PR2 task 2.7/2.8): `_resolve_token_usage`/`render()`'s
# pre-existing behavior must stay byte-identical -- `stage_timing.json` must
# have ZERO influence on token resolution, and no new exception path may be
# introduced for missing/malformed `stage_timing.json`.
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# Phase 4 scenario tests interleaved at the resolver/render layer (spec #326):
# inline dispatch with no duration signal, auto-simulator entirely absent,
# and the mid-run-hard-stop data-preservation guarantee.
# ---------------------------------------------------------------------------


def test_scenario_inline_dispatch_no_duration_signal_renders_with_absent_duration(tmp_path, monkeypatch):
    run_dir = _prepare_render_ready_run_dir(tmp_path)
    (run_dir / "token_usage.json").write_text(
        json.dumps({"historical": {"total": 50}}), encoding="utf-8"
    )
    assert not (run_dir / "stage_timing.json").exists()

    captured: dict = {}

    def _spy_render_llm_analysis(*args, **kwargs):
        captured.update(kwargs)
        html_path = tmp_path / "html" / "fake.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(report_pipeline_module, "render_llm_analysis", _spy_render_llm_analysis)

    html_path = render(run_dir, output_dir=tmp_path / "html")

    assert html_path.exists()
    by_stage = {entry["stage"]: entry for entry in captured["stage_breakdown"]}
    assert by_stage["historical"]["duration_seconds"] is None
    assert by_stage["historical"]["duration_source"] is None
    assert by_stage["historical"]["tokens_total"] == 50




def test_scenario_mid_run_hard_stop_preserves_completed_stages_data_on_disk(tmp_path):
    """Spec #326: historical+inference complete and record usage/duration,
    then the run stops (validation retries exhausted) before `render` is ever
    called -- the two completed stages' data must not be discarded."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    report_pipeline_module.record_token_usage(run_dir, "historical", total=111)
    report_pipeline_module.record_stage_timing(run_dir, "historical", seconds=10.0)
    report_pipeline_module.record_token_usage(run_dir, "inference", total=222)
    report_pipeline_module.record_stage_timing(run_dir, "inference", seconds=20.0)

    # Simulate the hard stop: expert-alignment exhausts validation retries,
    # so `render()` is never invoked for this run.

    token_usage_on_disk = json.loads((run_dir / "token_usage.json").read_text(encoding="utf-8"))
    stage_timing_on_disk = json.loads((run_dir / "stage_timing.json").read_text(encoding="utf-8"))

    assert token_usage_on_disk["historical"] == {"total": 111}
    assert token_usage_on_disk["inference"] == {"total": 222}
    assert stage_timing_on_disk["historical"] == {"duration_seconds": 10.0}
    assert stage_timing_on_disk["inference"] == {"duration_seconds": 20.0}


# --- El modelo predictivo mide severidad, no frecuencia ----------------------------------


def test_the_predictive_path_never_ranks_vanos_by_event_count():
    """`UITI_VANO` es el objetivo del modelo; `N_APARICIONES` no lo es.

    El camino predictivo corria CUATRO escenarios y dos seleccionaban los vanos por
    conteo de eventos. Eso le pedia al modelo que explicara una poblacion elegida por
    una magnitud que el no predice: sus rankings SHAP salen siempre del mismo objetivo
    -- UITI acumulado --, pero el informe los presentaba lado a lado como si fueran dos
    lecturas distintas del modelo. Ademas duplicaba el costo: cuatro pasadas de SHAP y
    cuatro grafos reconstruidos por circuito, para dos respuestas al mismo objetivo.

    La frecuencia sigue siendo un dato del caso, pero DESCRIPTIVO: le pertenece al
    historiador, que la lee de los eventos y no del modelo.
    """
    fuente = Path(report_pipeline_module.__file__).read_text(encoding="utf-8")
    culpables = [l.strip() for l in fuente.splitlines()
                 if "N_APARICIONES" in l and not l.strip().startswith("#")]

    assert not culpables, (
        "el camino predictivo vuelve a seleccionar vanos por conteo de eventos: "
        f"{culpables}"
    )


def test_the_inference_context_is_built_on_the_mil_model_not_on_mgcecdl():
    """El contexto que `prepare()` persiste tiene que declarar el modelo MIL.

    Aqui vivian cinco pruebas que fijaban la persistencia de figuras y grafos SHAP.
    Ese camino se retiro con MGCECDL, y con el se fueron por ahora las figuras de la
    seccion predictiva: el MIL no produce SHAP, y su equivalente visual -- barras de
    relevancia por vano y el grafo de sus propias compuertas -- esta pendiente. Lo que
    esta prueba si fija es lo que NO puede volver: que el informe se arme sobre el
    modelo por filas.
    """
    fuente = Path(report_pipeline_module.__file__).read_text(encoding="utf-8")
    llamadas = [l.strip() for l in fuente.splitlines()
                if not l.strip().startswith("#")
                and ("cargar_modelo_mgcecdl" in l or "escalar_features_minmax_mgcecdl" in l)]

    assert not llamadas, f"el pipeline volvio a cargar MGCECDL: {llamadas}"
    assert "construir_contexto_inferencia_mil" in fuente
