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
        `l1_state.json` bookkeeping file under a fresh run_dir. Also loads
        the MIL bag model once and runs the inference layer and the
        automatic min/max sensitivity simulator (`auto-simulator.bc.json` +
        `auto_simulation_assets.json`), both degrading to a no-op when no
        model artifact is available. Fails fast with `ReportPipelineError`
        if the circuit does not exist or the resolved window has zero
        events — no context is built and no run_dir is created in either
        case.

    prepare_expert_alignment(run_dir, *, pdf_discussions_path=None)
        Reads the historical and inference agents' VALIDATED outputs
        (`historical.out.json`, `inference.out.json` — written by the
        interactive Skills after `agent_tools.*.validate` returns `ok:
        true`), pools report dates from them plus the circuit's critical
        points, matches the already-extracted PDF-discussion xlsx table
        (`reports/analysis-documents/tabla_pdfs_intervalo_*.xlsx` — built by
        the separate, out-of-scope agent-native PDF-discussion batch runbook,
        `chec_local_interpreter.pdf_discussion_pipeline` plus
        `agent_tools.pdf_discussion`, design D5) against the circuit, and
        builds `expert-alignment.bc.json`. Fails fast with `ReportPipelineError` if
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
        `plotting.render_llm_analysis`, merging in the 5
        `automatic_simulation_*` kwargs from the optional auto-simulator
        sidecar/agent-output files when present (all `None` otherwise, same
        degrade shape as the inference-simulator sidecar), returning the
        HTML `Path`. Fails fast with `ReportPipelineError` if the
        expert-alignment output is missing/invalid — `render_llm_analysis`
        is never called in that case.

`runs_root` (on `prepare`), `pdf_discussions_path` (on
`prepare_expert_alignment`), and `output_dir` (on `render`) are additive,
optional keyword-only parameters beyond the design's documented signatures,
needed so tests never write into the real `reports/` tree. All default to
the design's proposed locations when omitted.
"""

from __future__ import annotations

import io
import json
import math
import os
import warnings
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import matplotlib

# Force a non-interactive backend BEFORE any transitive import below pulls in
# `matplotlib.pyplot` (e.g. `chec_impacto.data`/`chec_impacto.interpretability
# .circuit_analysis`, whose `graficar_barras_y_radar` calls `plt.show()`
# twice per scenario). Without this, running this pipeline outside pytest
# (only `tests/conftest.py` sets `matplotlib.use("Agg")`, for test isolation)
# would try to pop GUI windows or hang on a headless/server environment.
# Must run before the first `import matplotlib.pyplot` anywhere in the
# process, since the backend is resolved on first use.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 (must follow matplotlib.use("Agg"))
import numpy as np
import pandas as pd

from chec_impacto.data import preparar_splits_estratificados, procesar_dataset_completo
from chec_impacto.interpretability.circuit_analysis import (
    KernelShapTopVarsExtractor,
    agrupar_por_vano,
    construir_contexto_escenario_inferencia,
    construir_modos_chec,
    graficar_barras_y_radar,
)
from chec_impacto.training import (
    predict_classification,
    resolve_training_device,
)
from chec_local_interpreter.agent_output import ReportPipelineError, load_validated_agent_output
from chec_local_interpreter.attribution import enrich_critical_points
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.mil_inferencia import (
    METRICA as _METRICA_MIL,
    UNIDAD as _UNIDAD_MIL,
    cargar_recursos_mil,
    construir_contexto_inferencia_mil,
    knobs_desde_datos,
)
from chec_local_interpreter.config import (
    CriticalityThresholds,
    DEFAULT_DATA_PATH,
    DEFAULT_MODEL_BASENAME,
    DEFAULT_MODEL_DIR,
    DEFAULT_OPTUNA_STUDY_PATH,
    DEFAULT_VARIABLES_SELECCION_PATH,
    SHAP_RANDOM_STATE,
    _modelo_mas_reciente,
    project_root,
)
from chec_local_interpreter.context_builder import (
    build_context_package,
    save_json_artifact,
    vano_series_records,
)
from chec_local_interpreter.costs import build_auto_simulation_cost_context, load_cost_items
from chec_local_interpreter.critical_points import (
    build_daily_series,
    compute_daily_features,
    detect_critical_periods,
    detect_point_reasons,
    rank_critical_points,
    scaled_max_critical_points,
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
    normalizar_reporte_previo_como_matches,
    seleccionar_reporte_previo_mas_reciente,
    seleccionar_top_coincidencias_temporales,
)
from chec_local_interpreter.plotting import render_llm_analysis
from chec_local_interpreter.simulator import (
    simulate_automatic_minmax_sensitivity,
    simulate_suggested_vano_risk,
    simulate_top_softmax_curves,
)

# Mirrors the notebook's own defaults (`TOP_N_VANOS`/`TOP_K_VARS`/
# `FILTRO_UITI_MAX`/`VENTANA_CLIMATICA_HORAS` in
# `the retired interactive notebook`), preserved
# for parity since this change does not introduce a new tuning surface.
# `TOP_N_VANOS` is interpreted as a percentile (97 => vanos with metric >=
# P97) and is deliberately passed as BOTH `top_n_vanos` and
# `top_vanos_percentile`, matching the notebook's own call.
_TOP_N_VANOS_PERCENTILE = 97
_TOP_K_VARS = 20
_FILTRO_UITI_MAX = None
_VENTANA_CLIMATICA_HORAS = 12

# Kernel SHAP tuning, mirrors the same notebook cell's
# `SHAP_BACKGROUND_SIZE`/`SHAP_NSAMPLES`/`SHAP_BATCH_SIZE` defaults.
# `SHAP_RANDOM_STATE` itself lives in `config.py` (task 1.1) and is threaded
# explicitly into every `KernelShapTopVarsExtractor(...)` call below (task 2.2).
_SHAP_BACKGROUND_SIZE = 40
_SHAP_NSAMPLES = 80
_SHAP_BATCH_SIZE = 512

# No automatic simulator in this change: `escenarios` is always empty and
# `modelo` is a fixed placeholder label rather than a real model name.
_NO_SIMULATOR_MODEL_LABEL = "sin_simulador_automatico"

DEFAULT_RUNS_ROOT = project_root() / "reports" / "interpretability" / "runs"

# Directory conventionally populated by the (out-of-scope in this change)
# PDF-discussion *extraction* batch runbook
# (`chec_local_interpreter.pdf_discussion_pipeline` + `agent_tools.pdf_discussion`,
# design D5), which writes `tabla_pdfs_intervalo_*.xlsx` there. This
# orchestrator only READS that already-built table — it never touches PDFs
# itself.
DEFAULT_PDF_DISCUSSIONS_DIR = project_root() / "reports" / "analysis-documents"
_PDF_DISCUSSIONS_GLOB = "tabla_pdfs_intervalo_*.xlsx"

# Mirrors the notebook's `min(TOP_K_PDF_DATE_MATCHES, MAX_EXPERT_ROWS_FOR_LLM3)`
# (10, 30) => 10 (cell ~55 of the superseded
# `02_local_uiti_vano_interpretability_v3.ipynb`).
_TOP_K_PDF_DATE_MATCHES = 10

# Same `COSTOS ITEMS CONTRATOS.xlsx` file the deprecated notebook read via
# `COST_ITEMS_EXCEL_PATH` (cell ~59), resolved absolute against `project_root()`
# rather than `costs.DEFAULT_COST_ITEMS_PATH`'s cwd-relative default.
DEFAULT_COST_ITEMS_PATH = project_root() / "data" / "COSTOS ITEMS CONTRATOS.xlsx"

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





@dataclass
class SharedInferenceInputs:
    """`procesar_dataset_completo` calculado UNA vez por corrida de `prepare()`.

    De aqui salen el catalogo de controles del informe y los codificadores que la
    simulacion necesita, sin que cada consumidor rehaga el dataset.

    Aqui vivia ademas un escalador MinMax reajustado en cada corrida, con su propia
    advertencia de que podia diverger EN SILENCIO de la distribucion con la que se
    entreno el modelo si el CSV cambiaba. Se fue con MGCECDL: el modelo MIL puntua
    sobre la matriz de instancias RAW, asi que no hay escalado que pueda desalinearse.
    """

    datos: dict[str, Any]

def _prepare_shared_inference_inputs(
    source_path: str | Path,
    variables_path: str | Path,
) -> SharedInferenceInputs:
    """Compute `procesar_dataset_completo` ONCE, for `prepare()` to thread
    into both simulators via `shared_inputs` (design item 3). The stratified-
    split MinMax scaler fit itself is NOT computed here -- it is deferred to
    `SharedInferenceInputs.splits`'s first access (Judgment Day round 1 fix),
    so a circuit/window with zero surviving events never pays that cost (see
    `SharedInferenceInputs`'s own docstring for the full rationale).

    Uses the same deterministic parameters `_compute_inference_scenarios`/
    `_run_automatic_simulator` each used to recompute independently
    (`_FILTRO_UITI_MAX`, `_VENTANA_CLIMATICA_HORAS`).
    """
    source_path = Path(source_path)
    variables_path = Path(variables_path)

    with redirect_stdout(io.StringIO()):
        datos = procesar_dataset_completo(
            path_clima=source_path,
            path_variables_seleccion=variables_path,
            use_sampling=False,
            min_samples_per_codigo=5,
            target="UITI_VANO",
            filtro_uiti_max=_FILTRO_UITI_MAX,
            ventana_climatica_horas=_VENTANA_CLIMATICA_HORAS,
        )

    return SharedInferenceInputs(datos=datos)





# Kept as a module-private alias (rather than rewriting every call site)
# so this file's internal call sites stay untouched -- the implementation
# now lives in `agent_output.py` (task 1.3: shared, dependency-free module
# so `expert_alignment.py` can reuse it without a circular import, since
# this module already imports names FROM `expert_alignment.py` above).
_load_validated_agent_output = load_validated_agent_output

@dataclass(frozen=True)
class ReportPreflight:
    """Resolved report window without creating a run directory."""

    circuito: str
    fecha_inicio: str
    fecha_fin: str
    event_count: int

NOMBRE_MODELO_MIL = "mil_vano_ventana_v1.pt"
"""El artefacto que produce `05_mil_vano_ventana.ipynb`."""


def _contexto_inferencia_vacio(
    circuito: str, fecha_inicio: str, fecha_fin: str, fechas_interes: list[str]
) -> dict[str, Any]:
    """El contexto cuando no hay artefacto del modelo en disco.

    Declara el modelo y la unidad igual que el lleno, y `escenarios` vacio. Un contexto
    sin esas claves obligaria al agente a adivinar sobre que trabaja, y un informe que
    no distingue "el modelo no encontro nada" de "no habia modelo" es peor que uno que
    no habla del modelo.
    """
    return {
        "circuito_interes": str(circuito),
        "fecha_inicio": str(fecha_inicio),
        "fecha_fin": str(fecha_fin),
        "fechas_interes": [str(f) for f in fechas_interes or []],
        "modelo": _NO_SIMULATOR_MODEL_LABEL,
        "modelo_tipo": "mil_bolsas",
        "unidad": _UNIDAD_MIL,
        "metrica": _METRICA_MIL,
        "features": [],
        "ventanas": [],
        "escenarios": [],
        "sin_artefacto_de_modelo": True,
    }


def preflight(
    circuito: str,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    *,
    data_path: str | Path | None = None,
) -> ReportPreflight:
    """Validate and resolve the report window without writing artifacts.

    This is the shared adapter-facing preflight hook. It mirrors `prepare()`'s
    hard-fail checks but deliberately stops before run_dir creation, simulator
    setup, or context generation. `prepare()` remains authoritative and repeats
    the same checks before writing anything.
    """

    if (fecha_inicio is None) != (fecha_fin is None):
        raise ReportPipelineError(
            "fecha_inicio and fecha_fin must be given as a pair: provide both "
            "(pass-through) or omit both (defaults via circuit_date_range to "
            "the circuit's full range) -- exactly one date was given, which "
            "is a usage error and is never silently defaulted."
        )

    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    frame = load_dataset(source_path)

    if circuito not in available_circuits(frame):
        raise ReportPipelineError(f"Circuit not found in dataset: {circuito!r}")

    if fecha_inicio is None:
        start, end = circuit_date_range(frame, circuito)
    else:
        start, end = fecha_inicio, fecha_fin

    events_df = filter_events(frame, selected_circuitos=[circuito], start_date=start, end_date=end)
    if events_df.empty:
        raise ReportPipelineError(
            f"No events found for circuit {circuito!r} in window {start!r}..{end!r}"
        )

    return ReportPreflight(
        circuito=circuito,
        fecha_inicio=str(start),
        fecha_fin=str(end),
        event_count=int(len(events_df)),
    )

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

    `fecha_inicio`/`fecha_fin` are a PAIR (the `/reporte` Skill's argument
    contract): give both (pass-through, unchanged) or omit both (both default
    via `circuit_date_range` to the circuit's full range). Giving exactly one
    is a usage error, rejected before any other check.

    Returns the run_dir `Path`. Raises `ReportPipelineError` before any
    context is built or any run_dir is created if only one date bound is
    given, if the circuit does not exist in the dataset, or if the resolved
    date window has zero events.
    """
    if (fecha_inicio is None) != (fecha_fin is None):
        raise ReportPipelineError(
            "fecha_inicio and fecha_fin must be given as a pair: provide both "
            "(pass-through) or omit both (defaults via circuit_date_range to "
            "the circuit's full range) -- exactly one date was given, which "
            "is a usage error and is never silently defaulted."
        )

    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    frame = load_dataset(source_path)

    if circuito not in available_circuits(frame):
        raise ReportPipelineError(f"Circuit not found in dataset: {circuito!r}")

    if fecha_inicio is None:
        start, end = circuit_date_range(frame, circuito)
    else:
        start, end = fecha_inicio, fecha_fin

    events_df = filter_events(frame, selected_circuitos=[circuito], start_date=start, end_date=end)
    if events_df.empty:
        raise ReportPipelineError(
            f"No events found for circuit {circuito!r} in window {start!r}..{end!r}"
        )

    # `_new_run_dir` is created HERE -- right after the last hard-fail check
    # (zero events) and BEFORE the simulator runs (design decision 3, task
    # 3.3). The simulator itself never hard-fails (it degrades, see
    # `_run_inference_simulator`), so both circuit-not-found and zero-events
    # still never create an orphan run_dir, while the simulator has a
    # directory to persist figures into.
    run_dir = _new_run_dir(circuito, runs_root=runs_root)

    daily_df = build_daily_series(events_df)
    feature_df = compute_daily_features(daily_df)
    thresholds = CriticalityThresholds()
    reasons = detect_point_reasons(feature_df, thresholds)
    critical_points = rank_critical_points(feature_df, reasons, scaled_max_critical_points(start, end))
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
    # Loaded ONCE here and threaded into both simulators (design D2): the
    # inference/SHAP simulator and the automatic min/max simulator each used
    # El modelo del informe es el MIL por bolsas del cuaderno 05, el mismo que responde
    # el tablero del 06. Antes era MGCECDL por fila: dos modelos contestando la misma
    # pregunta, y un vano podia salir critico en uno y no en el otro sin que nada lo
    # explicara. El catalogo de controles se construye del mismo dataset y se hereda del
    # panel, para que informe y tablero ofrezcan las MISMAS palancas.
    # La ruta sale de `DEFAULT_MODEL_DIR` y no de una constante propia: es el mismo
    # directorio que el camino anterior consultaba, asi que apuntarlo a otro sitio
    # sigue significando "esta corrida no tiene modelo" -- que es como se prueba el
    # degradado y como se aisla una corrida de los artefactos del repo.
    recursos_mil = cargar_recursos_mil(
        ruta_modelo=Path(DEFAULT_MODEL_DIR) / NOMBRE_MODELO_MIL
    )
    # Computed ONCE here and threaded into both simulators (design item 3):
    # `_run_inference_simulator`/`_compute_inference_scenarios` and
    # `_run_automatic_simulator` each used to independently recompute
    # `procesar_dataset_completo` + re-fit the MinMax scaler with
    # byte-identical parameters. Guarded by `model is not None` (mirrors the
    # R3 no-op both simulators already degrade to) so a run with no trained
    # model artifact never pays this cost for nothing.
    shared_inputs = (
        _prepare_shared_inference_inputs(source_path, DEFAULT_VARIABLES_SELECCION_PATH)
        if recursos_mil is not None
        else None
    )
    if recursos_mil is not None and shared_inputs is not None:
        recursos_mil.knobs, recursos_mil.grupos_por_knob = knobs_desde_datos(
            shared_inputs.datos
        )
        recursos_mil.label_encoders = shared_inputs.datos.get("label_encoders", {})
        recursos_mil.max_values_imputed = shared_inputs.datos.get("max_values_imputed", {})

    # Sin artefacto del modelo el informe sigue saliendo, con la parte predictiva vacia:
    # la misma forma de hueco que tenia el camino anterior (R3), para que la falta de un
    # `.pt` no tumbe el diagnostico historico, que no lo necesita.
    render_assets: dict[str, Any] = {}
    if recursos_mil is None:
        inference_context = _contexto_inferencia_vacio(circuito, start, end, fechas_interes)
    else:
        inference_context = construir_contexto_inferencia_mil(
            recursos_mil,
            circuito=circuito,
            fecha_inicio=start,
            fecha_fin=end,
            fechas_interes=fechas_interes,
        )
        # La serie completa de los vanos que el diagnostico señalo. Verlos solo en la
        # ventana en que salieron criticos no distingue un problema cronico de uno que
        # aparecio el mes pasado, y esas dos cosas se atienden distinto.
        _identificados = list(dict.fromkeys(
            c["fid"]
            for e in inference_context["escenarios"]
            for c in e.get("vanos_criticos", [])
        ))
        inference_context["series_vanos_identificados"] = vano_series_records(
            events_df, circuito=circuito, fids=_identificados
        )

    save_json_artifact(historical_context, run_dir / "historical.bc.json")
    save_json_artifact(inference_context, run_dir / "inference.bc.json")
    if render_assets:
        # Only written when the simulator actually produced something to
        # persist -- `render()` (task 3.4) treats an absent sidecar as
        # "no inference figures for this run" (R1/R3 gap), never a crash.
        try:
            save_json_artifact(render_assets, run_dir / "inference_render_assets.json")
        except OSError as exc:
            # A disk-full/permission-revoked failure writing this sidecar
            # happens AFTER `_run_inference_simulator` already succeeded
            # (features/escenarios computed, PNGs/HTML already on disk) and
            # AFTER `historical.bc.json`/`inference.bc.json` are already
            # written above -- letting it propagate would crash an otherwise
            # fully successful run. `_build_inference_results` already
            # tolerates an absent sidecar (returns `None`, no crash), so this
            # degrades to "no inference figures for this run" instead of
            # aborting `prepare()`.
            warnings.warn(
                "No se pudo escribir el sidecar de activos de render para "
                f"'{circuito}': {exc}. La ejecución continúa sin figuras de "
                "inferencia renderizadas.",
                stacklevel=2,
            )

    # Runs AFTER `inference.bc.json` is persisted above: `_run_automatic_
    # simulator` reads it back to derive its candidate variable list (see
    # its own docstring for why -- D1/D2). Degrades to a no-op (returns
    # `None`, writes nothing) when `model is None`, mirroring the inference
    # simulator's own R3 gap. `shared_inputs` (design item 3) is the SAME
    # object passed to `_run_inference_simulator` above, guaranteeing this
    # simulator's `feature_scaler` is object-identical to the inference
    # simulator's.
    # Aqui corria el simulador automatico, un barrido min-max sobre MGCECDL. Se jubila
    # con el modelo: ese barrido es exactamente lo que `relevancia_hacia_uiti_minimo`
    # sustituyo en el cuaderno 06 -- con signo, y mirando el INTERIOR del rango y no
    # solo los extremos, que es donde 10 de los 15 controles numericos tienen su mejor
    # valor --, asi que su contenido ya viaja en la relevancia de cada escenario. El
    # flujo pasa de cuatro agentes a tres y el informe deja de traer dos tablas que
    # contestaban lo mismo con distinto metodo.

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

    The PDF-discussion *extraction* batch runbook
    (`chec_local_interpreter.pdf_discussion_pipeline` + `agent_tools.pdf_discussion`,
    design D5, which BUILDS `reports/analysis-documents/tabla_pdfs_intervalo_*.xlsx`)
    is out of scope for this change. This function only READS that
    already-built table and matches it against the circuit, exactly like the
    original (now-superseded) notebook flow
    (`the retired interactive notebook`, cell ~55):
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
        critical_points=state["critical_points"],
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

    # Prior-report reuse (sdd/reporte-graph-reuse, use case b): reuse the
    # newest qualifying prior run's OWN validated expert-alignment synthesis
    # as a second, lower-trust evidence source. Graceful no-op when there is
    # no qualifying prior run (`None`) or it has no usable evidence (`[]`) --
    # `pdf_expert_matches` is left byte-identical to today in that case (spec
    # "Graceful No-Op When No Qualifying Prior Run").
    prior_run_dir = seleccionar_reporte_previo_mas_reciente(run_dir)
    if prior_run_dir is not None:
        prior_report_matches = normalizar_reporte_previo_como_matches(
            prior_run_dir,
            state["circuito"],
            fechas_informe,
        )
        if prior_report_matches:
            pdf_expert_matches = pdf_expert_matches + prior_report_matches

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

def _build_inference_results(run_dir: Path) -> dict[str, Any] | None:
    """Read `run_dir/inference_render_assets.json` (task 3.2's sidecar) if
    present and rebuild the `inference_results` mapping `render_llm_analysis`
    expects: scenario key -> `{fig_barras, fig_radar, grafo_interactivo,
    contexto}`, every figure/graph path resolved to absolute against
    `run_dir`.

    Returns `None` (no crash) when the sidecar is absent -- the simulator
    either never ran (R3) or every scenario was skipped (R1), so there is
    nothing to render.
    """
    sidecar_path = run_dir / "inference_render_assets.json"
    if not sidecar_path.exists():
        return None

    render_assets = _read_json(sidecar_path)
    inference_bc = _read_json(run_dir / "inference.bc.json")
    escenarios_by_nombre = {
        escenario.get("nombre"): escenario
        for escenario in inference_bc.get("escenarios", [])
        if isinstance(escenario, dict)
    }

    def _resolve(value: str | None) -> str | None:
        return str(run_dir / value) if value is not None else None

    inference_results: dict[str, Any] = {}
    for scenario_key, asset in render_assets.items():
        if not isinstance(asset, dict):
            continue
        nombre = asset.get("nombre")
        inference_results[scenario_key] = {
            "fig_barras": _resolve(asset.get("fig_barras_png")),
            "fig_radar": _resolve(asset.get("fig_radar_png")),
            "grafo_interactivo": _resolve(asset.get("grafo_interactivo_html")),
            "contexto": escenarios_by_nombre.get(nombre, {}),
        }
    return inference_results


def _detect_llm_runtime() -> tuple[str, str]:
    """Best-effort detection of the orchestrating agent host and its model.

    The report is authored by whichever interactive agent runtime is driving
    this run (Claude Code) -- there is no LLM API call inside this module to
    introspect (see module docstring). The host is identifiable from
    environment variables the CLI sets on its subprocesses; the specific
    orchestrator *model* id is not exposed via any environment variable, so
    it can only come from an explicit override -- the invoking agent knows
    its own identity and is expected to pass `CHEC_LLM_MODEL` (or
    `render(..., llm_model=...)` directly).

    Returns `(provider, model)`, each `"Desconocido"` when undetected.
    """
    provider_override = os.environ.get("CHEC_LLM_PROVIDER", "").strip()
    model_override = os.environ.get("CHEC_LLM_MODEL", "").strip() or "Desconocido"

    if provider_override:
        return provider_override, model_override
    if os.environ.get("CLAUDECODE") == "1" or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        return "Claude Code", model_override
    return "Desconocido", model_override

TOKEN_USAGE_STAGES = ("historical", "inference", "auto-simulator", "expert-alignment")

def _validate_usage_measurement(*, total: Any = None, input: Any = None, output: Any = None) -> dict[str, int]:
    provided_total = total is not None
    provided_split = input is not None or output is not None
    if provided_total == provided_split or (provided_split and (input is None or output is None)):
        raise ValueError("provide exactly one usage shape: total OR input and output")
    values = {"total": total} if provided_total else {"input": input, "output": output}
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and float(value).is_integer() for value in values.values()):
        raise ValueError("token usage values must be non-negative integers")
    return {key: int(value) for key, value in values.items()}

def record_token_usage(run_dir: str | Path, stage: str, *, total: Any = None, input: Any = None, output: Any = None) -> dict[str, int]:
    if stage not in TOKEN_USAGE_STAGES:
        raise ValueError(f"unknown token usage stage: {stage}")
    measurement = _validate_usage_measurement(total=total, input=input, output=output)
    run_path = Path(run_dir)
    sidecar = run_path / "token_usage.json"
    try:
        existing = _read_json(sidecar) if sidecar.exists() else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReportPipelineError(f"invalid token usage sidecar: {exc}") from exc
    if not isinstance(existing, dict) or set(existing) - set(TOKEN_USAGE_STAGES):
        raise ReportPipelineError("token usage sidecar has an invalid shape or unknown stage")
    merged = dict(existing)
    merged[stage] = measurement
    run_path.mkdir(parents=True, exist_ok=True)
    temporary = sidecar.with_name(f".{sidecar.name}.tmp")
    temporary.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")
    os.replace(temporary, sidecar)
    return measurement

def _validate_duration_measurement(seconds: Any) -> dict[str, float]:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise ValueError("stage duration must be a non-negative real number")
    value = float(seconds)
    if not math.isfinite(value) or value < 0:
        raise ValueError("stage duration must be a non-negative real number")
    return {"duration_seconds": value}

def record_stage_timing(run_dir: str | Path, stage: str, *, seconds: Any) -> dict[str, float]:
    """Record `stage`'s wall-clock duration (seconds) into the optional
    `run_dir/stage_timing.json` sidecar, mirroring `record_token_usage`'s
    merge/atomic-write mechanics exactly. This function only PERSISTS a
    duration the caller measured itself (the orchestrator's own wall-clock
    around the stage dispatch, per design ADR-3) -- it never measures time.

    There is deliberately no `verify_stage_timing`/`verify-duration`
    counterpart: duration must never become a hard-failure gate (design
    ADR-1, spec "Duration capture never gates run success").
    """
    if stage not in TOKEN_USAGE_STAGES:
        raise ValueError(f"unknown stage timing stage: {stage}")
    measurement = _validate_duration_measurement(seconds)
    run_path = Path(run_dir)
    sidecar = run_path / "stage_timing.json"
    try:
        existing = _read_json(sidecar) if sidecar.exists() else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReportPipelineError(f"invalid stage timing sidecar: {exc}") from exc
    if not isinstance(existing, dict) or set(existing) - set(TOKEN_USAGE_STAGES):
        raise ReportPipelineError("stage timing sidecar has an invalid shape or unknown stage")
    merged = dict(existing)
    merged[stage] = measurement
    run_path.mkdir(parents=True, exist_ok=True)
    temporary = sidecar.with_name(f".{sidecar.name}.tmp")
    temporary.write_text(json.dumps(merged, sort_keys=True), encoding="utf-8")
    os.replace(temporary, sidecar)
    return measurement

@dataclass(frozen=True)
class TokenUsageVerification:
    expected_roles: tuple[str, ...]
    executed_roles: tuple[str, ...]
    valid_roles: tuple[str, ...]
    missing_measurements: tuple[str, ...]
    invalid_roles: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.missing_measurements and not self.invalid_roles

    def to_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "expected_roles": list(self.expected_roles), "executed_roles": list(self.executed_roles), "valid_roles": list(self.valid_roles), "missing_measurements": list(self.missing_measurements), "invalid_roles": list(self.invalid_roles), "errors": list(self.errors)}

def verify_token_usage(run_dir: str | Path, *, expected_roles: Sequence[str], executed_roles: Sequence[str]) -> TokenUsageVerification:
    expected = tuple(dict.fromkeys(expected_roles))
    executed = tuple(dict.fromkeys(executed_roles))
    errors = [f"unknown token usage stage: {role}" for role in (*expected, *executed) if role not in TOKEN_USAGE_STAGES]
    if expected:
        errors.extend(
            f"executed role is not expected: {role}"
            for role in executed
            if role in TOKEN_USAGE_STAGES and role not in expected
        )
    try:
        sidecar = _read_json(Path(run_dir) / "token_usage.json")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        sidecar = None
    if not isinstance(sidecar, dict):
        errors.append("token usage sidecar is missing or invalid")
        sidecar = {}
    errors.extend(f"unknown token usage stage: {role}" for role in sorted(set(sidecar) - set(TOKEN_USAGE_STAGES)))
    valid, invalid = [], []
    for role in executed:
        entry = sidecar.get(role)
        if entry is None:
            continue
        try:
            if not isinstance(entry, dict) or set(entry) - {"total", "input", "output"}:
                raise ValueError("invalid usage entry")
            _validate_usage_measurement(**entry)
        except ValueError:
            invalid.append(role)
        else:
            valid.append(role)
    missing = [role for role in executed if role not in valid]
    return TokenUsageVerification(expected, executed, tuple(valid), tuple(missing), tuple(invalid), tuple(errors))

def _resolve_token_usage(run_dir: Path) -> tuple[int, int, int, str, str]:
    """Resolve `(tokens_input, tokens_output, tokens_total, token_source, token_total_source)`
    for this run's agent-authored stages (design item 4), preferring REAL
    per-stage counts from an optional `run_dir/token_usage.json` sidecar over
    the char/4 estimate (replaces the estimate-only `_estimate_token_usage`).

    `token_usage.json` (optional -- written by the invoking agent after each
    Skill call whose runtime exposes usage, see `.claude/skills/report/
    SKILL.md` steps 3/4/4b/6) maps stage name
    (`"historical"`/`"inference"`/`"auto-simulator"`/`"expert-alignment"`) to
    EITHER `{"input": int, "output": int}` (a real input/output split) OR
    `{"total": int}` (a single combined count, for stages dispatched via
    Claude Code's `Agent` tool as real sub-agents, whose completion
    notification only reports a combined `subagent_tokens` figure with no
    input/output split available). Both shapes are valid per-stage and may be
    mixed across stages in the same sidecar file. Only stages that actually
    ran (i.e. have a `{stage}.bc.json` and/or a successfully-validated
    `{stage}.out.json` under `run_dir`) are considered; a stage absent from
    BOTH files contributes nothing to any total, same as the old
    estimate-only behavior.

    For any considered stage missing from the sidecar (or missing both the
    `"input"`/`"output"` keys and the `"total"` key), falls back to the
    char/4 estimate for THAT stage only -- applied as `characters // 4` (a
    common rule-of-thumb for English/Spanish text) over `*.bc.json` (input
    proxy) and `*.out.json`'s `data` (output proxy), same conservative
    undercount as before (excludes static prompt/playbook text).

    `tokens_total` accumulates, per considered stage, the best available
    number: the sidecar's `"total"` when present, else `input + output` (from
    either the sidecar's split or, when that stage wasn't measured at all,
    the char/4 estimate for that stage's input + output) -- it is always
    populated for every considered stage, mirroring the same
    "prefer sidecar, else char/4 estimate" precedence used for
    `tokens_input`/`tokens_output` individually.

    `token_source`:
    - `"measured"`: every considered stage's counts came from the sidecar
      (either shape).
    - `"mixed"`: the sidecar covers some, but not all, considered stages.
    - `"estimated"`: no sidecar (or it covers none of the considered
      stages) -- every count is the char/4 estimate. Also returned (as
      `(0, 0, 0, "estimated")`) when no stage produced any file at all.

    Any malformed sidecar degrades gracefully instead of raising (Judgment
    Day round 1 fix, matching this function's own documented "optional
    sidecar" contract): top-level invalid JSON is treated as an absent
    sidecar entirely, and a considered stage whose entry is not a dict, or
    whose `"input"`/`"output"`/`"total"` values are not coercible to `int`,
    falls back to the char/4 estimate for THAT stage only -- exactly as if
    the sidecar were absent for that stage.
    """
    sidecar_path = run_dir / "token_usage.json"
    sidecar: Any = {}
    if sidecar_path.exists():
        try:
            sidecar = _read_json(sidecar_path)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            sidecar = {}
    if not isinstance(sidecar, dict):
        sidecar = {}

    tokens_input = 0
    tokens_output = 0
    tokens_total = 0
    estimated_chars_in = 0
    estimated_chars_out = 0
    estimated_total_chars_in = 0
    estimated_total_chars_out = 0
    considered_count = 0
    split_measured_count = 0
    total_measured_count = 0

    for stage in ("historical", "inference", "auto-simulator", "expert-alignment"):
        bc_path = run_dir / f"{stage}.bc.json"
        chars_in = len(bc_path.read_text(encoding="utf-8")) if bc_path.exists() else None

        chars_out = None
        out_path = run_dir / f"{stage}.out.json"
        if out_path.exists():
            payload = _read_json(out_path)
            if isinstance(payload, dict) and payload.get("ok") is True:
                chars_out = len(json.dumps(payload.get("data"), ensure_ascii=False))

        if chars_in is None and chars_out is None:
            continue
        considered_count += 1

        stage_usage = sidecar.get(stage)
        stage_split_measured = False
        stage_total_measured = False
        if isinstance(stage_usage, dict) and "input" in stage_usage and "output" in stage_usage:
            try:
                stage_tokens_input = int(stage_usage["input"])
                stage_tokens_output = int(stage_usage["output"])
            except (TypeError, ValueError):
                pass
            else:
                tokens_input += stage_tokens_input
                tokens_output += stage_tokens_output
                tokens_total += stage_tokens_input + stage_tokens_output
                stage_split_measured = True
        elif isinstance(stage_usage, dict) and "total" in stage_usage:
            try:
                stage_tokens_total = int(stage_usage["total"])
            except (TypeError, ValueError):
                pass
            else:
                tokens_total += stage_tokens_total
                stage_total_measured = True

        if stage_split_measured:
            split_measured_count += 1
        if stage_split_measured or stage_total_measured:
            total_measured_count += 1
        else:
            # Fully unmeasured stage (neither shape present/valid) -- both
            # tokens_total AND tokens_input/tokens_output fall back to the
            # char/4 estimate for this stage.
            estimated_total_chars_in += chars_in or 0
            estimated_total_chars_out += chars_out or 0

        if not stage_split_measured:
            # No input/output split available (either fully unmeasured, or
            # measured only via the "total"-only shape) -- tokens_input/
            # tokens_output individually still fall back to the char/4
            # estimate for this stage, even though tokens_total already has
            # a real number from the sidecar in the "total"-only case.
            estimated_chars_in += chars_in or 0
            estimated_chars_out += chars_out or 0

    tokens_input += estimated_chars_in // 4
    tokens_output += estimated_chars_out // 4
    tokens_total += estimated_total_chars_in // 4 + estimated_total_chars_out // 4

    if considered_count == 0 or split_measured_count == 0:
        token_source = "estimated"
    elif split_measured_count == considered_count:
        token_source = "measured"
    else:
        token_source = "mixed"

    if considered_count == 0 or total_measured_count == 0:
        token_total_source = "estimated"
    elif total_measured_count == considered_count:
        token_total_source = "measured"
    else:
        token_total_source = "mixed"

    return tokens_input, tokens_output, tokens_total, token_source, token_total_source

def _resolve_stage_timing(run_dir: Path) -> dict[str, float | None]:
    """Resolve each of `TOKEN_USAGE_STAGES`' wall-clock duration from the
    optional `run_dir/stage_timing.json` sidecar (design ADR-1/ADR-3),
    mirroring `_resolve_token_usage`'s sidecar-degrade contract: absent file,
    invalid top-level JSON, or a non-dict top-level value all degrade to
    every stage resolving `None` (never raise); a single stage's entry that
    is not a dict, or whose `"duration_seconds"` is missing/non-numeric/
    negative/non-finite, degrades to `None` for THAT stage only.

    Unlike token usage, a missing/invalid duration is never estimated -- it
    is always either the measured wall-clock value or `None`.
    """
    sidecar_path = run_dir / "stage_timing.json"
    sidecar: Any = {}
    if sidecar_path.exists():
        try:
            sidecar = _read_json(sidecar_path)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            sidecar = {}
    if not isinstance(sidecar, dict):
        sidecar = {}

    result: dict[str, float | None] = {}
    for stage in TOKEN_USAGE_STAGES:
        entry = sidecar.get(stage)
        value: float | None = None
        if isinstance(entry, dict):
            raw = entry.get("duration_seconds")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                candidate = float(raw)
                if math.isfinite(candidate) and candidate >= 0:
                    value = candidate
        result[stage] = value
    return result

def _resolve_stage_breakdown(run_dir: Path) -> list[dict[str, Any]]:
    """Resolve a per-stage `{stage, tokens_total, token_source,
    duration_seconds, duration_source}` breakdown for each CONSIDERED agent
    stage (design item "per-stage breakdown"; PR2 of the report-usage-
    accounting chain).

    Additive-only per the design's explicit resolver decision: this
    duplicates ONLY `_resolve_token_usage`'s minimal "considered stage" gate
    (has a `{stage}.bc.json` and/or an ok `{stage}.out.json`) and its char/4
    estimate math for a SINGLE stage at a time -- it does not call or modify
    `_resolve_token_usage`, which stays byte-for-byte untouched. Duration is
    joined from `_resolve_stage_timing` and is measured-or-absent, never
    estimated (design ADR-1/ADR-3).

    A stage entirely absent from `run_dir` (e.g. `auto-simulator` skipped)
    is OMITTED from the returned list rather than errored or shown as a
    failed row -- same "considered stage" gate `_resolve_token_usage` uses.
    """
    sidecar_path = run_dir / "token_usage.json"
    sidecar: Any = {}
    if sidecar_path.exists():
        try:
            sidecar = _read_json(sidecar_path)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            sidecar = {}
    if not isinstance(sidecar, dict):
        sidecar = {}

    stage_durations = _resolve_stage_timing(run_dir)

    breakdown: list[dict[str, Any]] = []
    for stage in TOKEN_USAGE_STAGES:
        bc_path = run_dir / f"{stage}.bc.json"
        chars_in = len(bc_path.read_text(encoding="utf-8")) if bc_path.exists() else None

        chars_out = None
        out_path = run_dir / f"{stage}.out.json"
        if out_path.exists():
            payload = _read_json(out_path)
            if isinstance(payload, dict) and payload.get("ok") is True:
                chars_out = len(json.dumps(payload.get("data"), ensure_ascii=False))

        if chars_in is None and chars_out is None:
            continue  # not considered -- stage never ran, omit entirely

        stage_usage = sidecar.get(stage)
        tokens_total: int | None = None
        token_source = "estimated"
        if isinstance(stage_usage, dict) and "input" in stage_usage and "output" in stage_usage:
            try:
                candidate_total = int(stage_usage["input"]) + int(stage_usage["output"])
            except (TypeError, ValueError):
                pass
            else:
                tokens_total = candidate_total
                token_source = "measured"
        if tokens_total is None and isinstance(stage_usage, dict) and "total" in stage_usage:
            try:
                candidate_total = int(stage_usage["total"])
            except (TypeError, ValueError):
                pass
            else:
                tokens_total = candidate_total
                token_source = "measured"
        if tokens_total is None:
            tokens_total = (chars_in or 0) // 4 + (chars_out or 0) // 4
            token_source = "estimated"

        duration_seconds = stage_durations.get(stage)
        duration_source = "measured" if duration_seconds is not None else None

        breakdown.append(
            {
                "stage": stage,
                "tokens_total": tokens_total,
                "token_source": token_source,
                "duration_seconds": duration_seconds,
                "duration_source": duration_source,
            }
        )

    return breakdown

def _resolve_elapsed_seconds(run_dir: Path) -> float | None:
    """Resolve this run's total wall-clock execution time by parsing the
    UTC timestamp encoded in `run_dir.name` (written by `_new_run_dir` as
    `datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")`) and diffing it
    against the current time.

    Degrades gracefully -- returns `None`, never raises -- when `run_dir.name`
    does not match that exact format (e.g. a caller-supplied `tmp_path` in
    tests, or any run_dir not created by `_new_run_dir`).
    """
    try:
        parsed_start = datetime.strptime(run_dir.name, "%Y%m%dT%H%M%S%f").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - parsed_start).total_seconds()

def _render_output_filename(state: dict[str, Any], run_dir: Path) -> str:
    """Return the stable HTML filename for a prepared report run.

    The run directory is the report identity. Using it in the filename makes
    repeated renders idempotent: a metadata-less preliminary render and a later
    metadata-enriched render replace the same artifact instead of producing two
    same-window HTML files.
    """
    circuito = str(state.get("circuito") or "TODOS")
    start_str = str(state.get("fecha_inicio") or "inicio").replace("-", "")
    end_str = str(state.get("fecha_fin") or "fin").replace("-", "")
    run_id = run_dir.name or "run"
    return f"{circuito}_{start_str}_{end_str}_{run_id}.html"

def render(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
    tokens_total: int | None = None,
    elapsed_seconds: float | None = None,
        require_measured_usage: bool = False,
        expected_roles: Sequence[str] = (),
        executed_roles: Sequence[str] = (),
) -> Path:
    """Read all three validated outputs from `run_dir` and render the final
    HTML report via `plotting.render_llm_analysis`.

    Reconstructs `raw_df`/`daily_df` deterministically from `l1_state.json`
    (data_path + circuito + resolved date window) rather than serializing
    DataFrames to disk, so the run_dir stays plain-JSON. `render()` itself
    stays model-free: `inference_results` (task 3.4) is rebuilt purely from
    persisted paths in `inference_render_assets.json`, never by reloading the
    MIL model or recomputing the relevance sweep.

    `llm_provider`/`llm_model` identify, in the report header, which agent
    host and which orchestrator model produced this run. `llm_provider`
    defaults to autodetection (`_detect_llm_runtime`, Claude Code via
    environment variables); `llm_model` has no reliable environment signal
    and defaults to `"Desconocido"` unless the caller passes it explicitly
    or sets `CHEC_LLM_MODEL`. `tokens_input`/
    `tokens_output` precedence (design item 4): an explicit kwarg wins for
    its own side; whichever side is omitted (`None`) falls back to
    `_resolve_token_usage` (real per-stage counts from `run_dir/
    token_usage.json` when present, else its deterministic file-size-based
    char/4 estimate). When exactly one side is given explicitly, that side
    is trusted/precise and the combined `token_source` is never downgraded
    to `"estimated"` on its account -- it is `"measured"` only when the
    resolved side is also measured, `"mixed"` otherwise. The resolved source
    is labeled `measured`/`mixed`/`estimated` in the report header via the
    `token_source` kwarg passed to `render_llm_analysis`.

    `tokens_total` and `elapsed_seconds` follow the same "explicit kwarg wins,
    else resolve" precedence, independently of the `tokens_input`/
    `tokens_output` precedence above: `tokens_total` falls back to
    `_resolve_token_usage`'s 4th return value (the total across every
    considered stage, including stages measured only via the sidecar's
    `{"total": int}` shape -- e.g. sub-agents dispatched via Claude Code's
    `Agent` tool, which only report a single combined count); `elapsed_seconds`
    falls back to `_resolve_elapsed_seconds(run_dir)`, which itself may return
    `None` (propagated through -- the header rendering simply omits that
    line, same degrade-gracefully pattern as the token fields being `None`).
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

    detected_provider, detected_model = _detect_llm_runtime()
    resolved_input, resolved_output, resolved_total, resolved_source, resolved_total_source = _resolve_token_usage(run_dir)
    if tokens_input is None and tokens_output is None:
        # Neither kwarg given -- resolve both from `run_dir` (sidecar-real >
        # char/4 estimate); the resolved source is authoritative.
        tokens_input, tokens_output, token_source = resolved_input, resolved_output, resolved_source
    elif tokens_input is None or tokens_output is None:
        # Exactly one kwarg given explicitly (Judgment Day round 1 fix): that
        # side is itself a precise/authoritative count from the caller, so it
        # must never be mislabeled by whatever `_resolve_token_usage` reports
        # for the OTHER (omitted) side. Only fill in the omitted side from
        # resolution, and combine the label: "measured" when the resolved
        # side is also measured, "mixed" otherwise -- never "estimated",
        # since at least one side here is caller-provided/trusted.
        tokens_input = resolved_input if tokens_input is None else tokens_input
        tokens_output = resolved_output if tokens_output is None else tokens_output
        token_source = "measured" if resolved_source == "measured" else "mixed"
    else:
        token_source = "measured"

    if tokens_total is None:
        # A char/4 fallback is useful for the split line as a partial artifact
        # estimate, but it is not defensible as the whole-run aggregate. Expose
        # a total only when every considered stage supplied measured accounting.
        tokens_total = resolved_total if resolved_total_source == "measured" else None
        token_total_source = resolved_total_source
    else:
        token_total_source = "measured"
    if elapsed_seconds is None:
        elapsed_seconds = _resolve_elapsed_seconds(run_dir)

    kwargs: dict[str, Any] = {
        "start_date": state["fecha_inicio"],
        "end_date": state["fecha_fin"],
        "inference_results": _build_inference_results(run_dir),
        "inference_analysis": inference_data,
        "expert_alignment_analysis": expert_alignment_data,
        "expert_alignment_matches": None,
        "all_circuits_df": frame,
        "llm_provider": llm_provider or detected_provider,
        "llm_model": llm_model or detected_model,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_total": tokens_total,
        "token_source": token_source,
        "token_total_source": token_total_source,
        "elapsed_seconds": elapsed_seconds,
        "output_filename": _render_output_filename(state, run_dir),
        "stage_breakdown": _resolve_stage_breakdown(run_dir),
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
