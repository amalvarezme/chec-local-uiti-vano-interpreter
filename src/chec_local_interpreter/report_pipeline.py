"""Pure-Python orchestrator for the `/reporte` pipeline (Slice B).

Splits the end-to-end report flow into resumable stages so the interactive
Claude Code agent Skills (historical, inference, expert-alignment) sit
BETWEEN Python stages, not inside them (design: "Control-flow boundary").
Every stage here is deterministic and reads/writes plain JSON under a
per-run directory ("run_dir") on disk — no LLM call ever happens in this
module.

Stages:
    prepare(circuito, fecha_inicio=None, fecha_fin=None, *, data_path=None)
        Loads/filters the dataset for one circuit, defaults the date range
        via `data_loader.circuit_date_range` when either bound is missing,
        runs critical-point detection, and writes the two raw context
        payloads (`historical.bc.json`, `inference.bc.json`) plus an
        `l1_state.json` bookkeeping file under a fresh run_dir. Fails fast
        with `ReportPipelineError` if the circuit does not exist or the
        resolved window has zero events — no context is built and no
        run_dir is created in either case.

    prepare_expert_alignment(run_dir, *, pdf_discussions_path=None)
        Reads the historical and inference agents' VALIDATED outputs
        (`historical.out.json`, `inference.out.json` — written by the
        interactive Skills after `agent_tools.*.validate` returns `ok:
        true`), pools report dates from them plus the circuit's critical
        points, matches the already-extracted PDF-discussion xlsx table
        (`reports/analysis-documents/tabla_pdfs_intervalo_*.xlsx` — built by
        the separate, out-of-scope `01_pdf_discussion_table_from_pdfs.ipynb`
        notebook) against the circuit, and builds
        `expert-alignment.bc.json`. Fails fast with `ReportPipelineError` if
        either agent's validated output is missing or marked `ok: false`
        (schema/guardrail and provenance failures are indistinguishable at
        this layer — both are simply `ok: false` from the combined L1
        `validate()` contract, so a retries-exhausted circuit never reaches
        this stage with a usable file). The PDF-discussion match is a
        graceful-degradation path, not a hard failure: a missing/empty xlsx
        or zero rows for the circuit simply yields `pdf_expert_matches=[]`.

    render(run_dir, *, output_dir=None)
        Reads all three validated outputs (historical, inference,
        expert-alignment) from the run_dir and calls
        `plotting.render_llm_analysis` with no `automatic_simulation_*`
        kwargs (no simulator in this change), returning the HTML `Path`.
        Fails fast with `ReportPipelineError` if the expert-alignment
        output is missing/invalid — `render_llm_analysis` is never called
        in that case.

`runs_root` (on `prepare`), `pdf_discussions_path` (on
`prepare_expert_alignment`), and `output_dir` (on `render`) are additive,
optional keyword-only parameters beyond the design's documented signatures,
needed so tests never write into the real `reports/` tree. All default to
the design's proposed locations when omitted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from chec_impacto.interpretability.circuit_analysis import construir_contexto_inferencia
from chec_local_interpreter.attribution import enrich_critical_points
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.config import CriticalityThresholds, DEFAULT_DATA_PATH, project_root
from chec_local_interpreter.context_builder import build_context_package, save_json_artifact
from chec_local_interpreter.critical_points import (
    build_daily_series,
    compute_daily_features,
    detect_critical_periods,
    detect_point_reasons,
    rank_critical_points,
)
from chec_local_interpreter.data_loader import (
    available_circuits,
    circuit_date_range,
    filter_events,
    load_dataset,
)
from chec_local_interpreter.expert_alignment import (
    cargar_discussiones_pdf_excel,
    construir_contexto_expert_alignment,
    extraer_fechas_informe,
    filtrar_discussiones_por_circuito,
    seleccionar_top_coincidencias_temporales,
)
from chec_local_interpreter.plotting import render_llm_analysis

# Mirrors the notebook's own defaults (`TOP_N_VANOS`/`TOP_K_VARS`/
# `FILTRO_UITI_MAX`/`VENTANA_CLIMATICA_HORAS` in
# `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`), preserved
# for parity since this change does not introduce a new tuning surface.
# `TOP_N_VANOS` is interpreted as a percentile (97 => vanos with metric >=
# P97) and is deliberately passed as BOTH `top_n_vanos` and
# `top_vanos_percentile`, matching the notebook's own call.
_TOP_N_VANOS_PERCENTILE = 97
_TOP_K_VARS = 20
_FILTRO_UITI_MAX = None
_VENTANA_CLIMATICA_HORAS = 12

# No automatic simulator in this change: `escenarios` is always empty and
# `modelo` is a fixed placeholder label rather than a real model name.
_NO_SIMULATOR_MODEL_LABEL = "sin_simulador_automatico"

DEFAULT_RUNS_ROOT = project_root() / "reports" / "interpretability" / "runs"

# Directory conventionally populated by the (out-of-scope in this change)
# PDF-discussion *extraction* notebook (`01_pdf_discussion_table_from_pdfs.ipynb`),
# which writes `tabla_pdfs_intervalo_*.xlsx` there. This orchestrator only
# READS that already-built table — it never touches PDFs itself.
DEFAULT_PDF_DISCUSSIONS_DIR = project_root() / "reports" / "analysis-documents"
_PDF_DISCUSSIONS_GLOB = "tabla_pdfs_intervalo_*.xlsx"

# Mirrors the notebook's `min(TOP_K_PDF_DATE_MATCHES, MAX_EXPERT_ROWS_FOR_LLM3)`
# (10, 30) => 10 (cell ~55 of the superseded
# `02_local_uiti_vano_interpretability_v3.ipynb`).
_TOP_K_PDF_DATE_MATCHES = 10


class ReportPipelineError(ValueError):
    """Raised when the report pipeline cannot proceed for a given circuit or run_dir.

    Subclasses `ValueError` so existing `except ValueError` handling upstream
    keeps working, while giving callers/tests a specific type to catch.
    """


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve_pdf_discussions_path(pdf_discussions_path: str | Path | None = None) -> Path:
    """Resolve "the" PDF-discussion xlsx table for this run.

    If an explicit path is given, use it as-is (test isolation / callers that
    already know which file to use). Otherwise glob
    `DEFAULT_PDF_DISCUSSIONS_DIR` for `tabla_pdfs_intervalo_*.xlsx` and, when
    more than one candidate matches, deterministically pick the
    lexicographically last one (mirrors the notebook's own
    `_modelo_mas_reciente` convention for resolving "the" file among several
    dated candidates: `sorted(candidates)[-1]`). When no candidate exists,
    return a non-existent sentinel path so `cargar_discussiones_pdf_excel`'s
    own not-found handling triggers graceful degradation.
    """
    if pdf_discussions_path is not None:
        return Path(pdf_discussions_path)
    candidates = sorted(DEFAULT_PDF_DISCUSSIONS_DIR.glob(_PDF_DISCUSSIONS_GLOB))
    if not candidates:
        return DEFAULT_PDF_DISCUSSIONS_DIR / _PDF_DISCUSSIONS_GLOB.replace("*", "not-found")
    return candidates[-1]


def _new_run_dir(circuito: str, *, runs_root: str | Path | None = None) -> Path:
    root = Path(runs_root) if runs_root is not None else DEFAULT_RUNS_ROOT
    safe_name = canonical_circuit_identity(circuito)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    run_dir = root / safe_name / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _load_validated_agent_output(run_dir: Path, agent_name: str) -> dict[str, Any]:
    """Read `{agent_name}.out.json` and require the combined L1 `validate()`
    success shape `{"ok": true, "data": {...}}`.

    Raises `ReportPipelineError` if the file is absent (the Skill never
    produced a validated output — e.g. retries exhausted) or present but not
    a successful envelope (`ok` missing/false, or malformed JSON shape).
    """
    path = run_dir / f"{agent_name}.out.json"
    if not path.exists():
        raise ReportPipelineError(
            f"Missing validated output for agent '{agent_name}' at {path} "
            "(the Skill has not produced a passing validate() result yet, "
            "or validation retries were exhausted without success)."
        )
    payload = _read_json(path)
    if not isinstance(payload, dict) or payload.get("ok") is not True or "data" not in payload:
        raise ReportPipelineError(
            f"Validated output for agent '{agent_name}' at {path} is not a "
            "successful envelope (expected {'ok': true, 'data': ...})."
        )
    return payload["data"]


def prepare(
    circuito: str,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    *,
    data_path: str | Path | None = None,
    runs_root: str | Path | None = None,
) -> Path:
    """Load/filter data for `circuito`, detect critical points, and write the
    historical + inference raw context payloads to a fresh run_dir.

    Returns the run_dir `Path`. Raises `ReportPipelineError` before any
    context is built or any run_dir is created if the circuit does not
    exist in the dataset, or if the resolved date window has zero events.
    """
    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    frame = load_dataset(source_path)

    if circuito not in available_circuits(frame):
        raise ReportPipelineError(f"Circuit not found in dataset: {circuito!r}")

    range_start, range_end = circuit_date_range(frame, circuito)
    start = fecha_inicio or range_start
    end = fecha_fin or range_end

    events_df = filter_events(frame, selected_circuitos=[circuito], start_date=start, end_date=end)
    if events_df.empty:
        raise ReportPipelineError(
            f"No events found for circuit {circuito!r} in window {start!r}..{end!r}"
        )

    daily_df = build_daily_series(events_df)
    feature_df = compute_daily_features(daily_df)
    thresholds = CriticalityThresholds()
    reasons = detect_point_reasons(feature_df, thresholds)
    critical_points = rank_critical_points(feature_df, reasons, thresholds.max_points)
    critical_points = enrich_critical_points(events_df, critical_points)
    critical_periods = detect_critical_periods(feature_df, thresholds)

    # Graphify enrichment failure is handled INSIDE build_context_package
    # (existing degrade-to-string behavior) — deliberately not wrapped here
    # so that existing degradation path is neither shadowed nor duplicated
    # (task 6.8).
    historical_context = build_context_package(
        events_df=events_df,
        daily_df=daily_df,
        critical_points=critical_points,
        critical_periods=critical_periods,
        selected_circuitos=[circuito],
        start_date=start,
        end_date=end,
        raw_df=events_df,
    )

    fechas_interes = [point["fecha_dia"] for point in critical_points]
    inference_context = construir_contexto_inferencia(
        circuito_interes=circuito,
        fecha_inicio=start,
        fecha_fin=end,
        fechas_interes=fechas_interes,
        top_n_vanos=_TOP_N_VANOS_PERCENTILE,
        top_k_vars=_TOP_K_VARS,
        filtro_uiti_max=_FILTRO_UITI_MAX,
        ventana_climatica_horas=_VENTANA_CLIMATICA_HORAS,
        features=[],
        base=events_df,
        escenarios=[],
        modelo=_NO_SIMULATOR_MODEL_LABEL,
        top_vanos_percentile=_TOP_N_VANOS_PERCENTILE,
    )

    run_dir = _new_run_dir(circuito, runs_root=runs_root)
    save_json_artifact(historical_context, run_dir / "historical.bc.json")
    save_json_artifact(inference_context, run_dir / "inference.bc.json")
    save_json_artifact(
        {
            "circuito": circuito,
            "fecha_inicio": start,
            "fecha_fin": end,
            "data_path": str(source_path),
            "critical_points": critical_points,
            "critical_periods": critical_periods,
        },
        run_dir / "l1_state.json",
    )
    return run_dir


def prepare_expert_alignment(
    run_dir: str | Path,
    *,
    pdf_discussions_path: str | Path | None = None,
) -> Path:
    """Build `expert-alignment.bc.json` from the historical and inference
    agents' validated outputs already written under `run_dir`, plus the
    already-extracted PDF-discussion xlsx table matched against the circuit.

    The PDF-discussion *extraction* notebook
    (`01_pdf_discussion_table_from_pdfs.ipynb`, which BUILDS
    `reports/analysis-documents/tabla_pdfs_intervalo_*.xlsx`) is out of scope
    for this change. This function only READS that already-built table and
    matches it against the circuit, exactly like the original notebook flow
    (`notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`, cell ~55):
    `cargar_discussiones_pdf_excel` -> `extraer_fechas_informe` ->
    `filtrar_discussiones_por_circuito` -> `seleccionar_top_coincidencias_temporales`.

    This is a graceful-degradation path, not a hard failure: if the xlsx
    table doesn't exist, is empty, or has zero rows for this circuit,
    expert-alignment still proceeds with `pdf_expert_matches=[]` (and
    `construir_contexto_expert_alignment` derives `modelo_experto_disponible:
    false` from that empty list) rather than raising.

    Returns `run_dir` (chainable, mirrors `prepare`'s return) rather than the
    artifact file path, so `render(prepare_expert_alignment(prepare(...)))`
    composes directly.
    """
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "l1_state.json")
    historical_data = _load_validated_agent_output(run_dir, "historical")
    inference_data = _load_validated_agent_output(run_dir, "inference")
    inference_context = _read_json(run_dir / "inference.bc.json")

    fechas_informe = extraer_fechas_informe(
        validation_data=historical_data,
        inference_validation_data=inference_data,
        critical_points=state.get("critical_points"),
        fecha_inicio=state["fecha_inicio"],
        fecha_fin=state["fecha_fin"],
    )

    resolved_pdf_path = _resolve_pdf_discussions_path(pdf_discussions_path)
    pdf_discussions_df, _pdf_discussion_warnings = cargar_discussiones_pdf_excel(resolved_pdf_path)

    pdf_expert_matches: list[dict[str, Any]] = []
    if not pdf_discussions_df.empty:
        pdf_discussions_circuit_df = filtrar_discussiones_por_circuito(pdf_discussions_df, state["circuito"])
        if not pdf_discussions_circuit_df.empty:
            pdf_expert_matches = seleccionar_top_coincidencias_temporales(
                fechas_informe=fechas_informe,
                pdf_df=pdf_discussions_circuit_df,
                circuito_interes=state["circuito"],
                top_k=_TOP_K_PDF_DATE_MATCHES,
            )

    context = construir_contexto_expert_alignment(
        circuito=state["circuito"],
        periodo_inicio=state["fecha_inicio"],
        periodo_fin=state["fecha_fin"],
        fechas_informe=fechas_informe,
        validation_data=historical_data,
        inference_validation_data=inference_data,
        pdf_expert_matches=pdf_expert_matches,
        inference_context_package=inference_context,
        variables_modelo_predictivo=None,
    )
    save_json_artifact(context, run_dir / "expert-alignment.bc.json")
    return run_dir


def render(run_dir: str | Path, *, output_dir: str | Path | None = None) -> Path:
    """Read all three validated outputs from `run_dir` and render the final
    HTML report via `plotting.render_llm_analysis` (no simulator kwargs).

    Reconstructs `raw_df`/`daily_df` deterministically from `l1_state.json`
    (data_path + circuito + resolved date window) rather than serializing
    DataFrames to disk, so the run_dir stays plain-JSON.
    """
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "l1_state.json")
    historical_data = _load_validated_agent_output(run_dir, "historical")
    inference_data = _load_validated_agent_output(run_dir, "inference")
    expert_alignment_data = _load_validated_agent_output(run_dir, "expert-alignment")

    frame = load_dataset(state["data_path"])
    events_df = filter_events(
        frame,
        selected_circuitos=[state["circuito"]],
        start_date=state["fecha_inicio"],
        end_date=state["fecha_fin"],
    )
    daily_df = build_daily_series(events_df)

    kwargs: dict[str, Any] = {
        "start_date": state["fecha_inicio"],
        "end_date": state["fecha_fin"],
        "inference_results": None,
        "inference_analysis": inference_data,
        "expert_alignment_analysis": expert_alignment_data,
        "expert_alignment_matches": None,
    }
    if output_dir is not None:
        kwargs["output_dir"] = output_dir

    return render_llm_analysis(
        historical_data,
        events_df,
        daily_df,
        state["critical_points"],
        [state["circuito"]],
        **kwargs,
    )
