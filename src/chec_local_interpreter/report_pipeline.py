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
        the MGCECDL model once and runs the inference/SHAP simulator and the
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
import os
import warnings
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    construir_contexto_inferencia,
    construir_modos_chec,
    graficar_barras_y_radar,
)
from chec_impacto.training import (
    cargar_estudio_optuna_mgcecdl,
    cargar_modelo_mgcecdl,
    escalar_features_minmax_mgcecdl,
    predict_classification,
    resolve_training_device,
)
from chec_local_interpreter.attribution import enrich_critical_points
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
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
from chec_local_interpreter.context_builder import build_context_package, save_json_artifact
from chec_local_interpreter.costs import build_auto_simulation_cost_context, load_cost_items
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
from chec_local_interpreter.simulator import (
    simulate_automatic_minmax_sensitivity,
    simulate_suggested_vano_risk,
    simulate_top_softmax_curves,
)

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


class _MGCECDLClassifierShapAdapter:
    """`predict_proba` adapter so Kernel SHAP can drive the MGCECDL classifier.

    Ported from the notebook's `MGCECDLClassifierShapAdapter`
    (`notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`, cell 35,
    deprecated in place).
    """

    def __init__(self, model: Any, device: Any) -> None:
        self.model = model
        self.device = device

    def predict_proba(self, values: Any) -> np.ndarray:
        values = np.asarray(values, dtype=np.float32)
        if values.ndim == 1:
            values = values.reshape(1, -1)
        return np.asarray(
            predict_classification(self.model, values, device=self.device)["fused_probs"],
            dtype=np.float64,
        )


def _seleccionar_vanos_por_percentil(
    tabla: pd.DataFrame, metric_col: str, percentile: float
) -> tuple[pd.DataFrame, float]:
    """Select vanos with `metric_col >= percentile` (ported from the notebook's
    `seleccionar_vanos_por_percentil`, cell 37, deprecated in place)."""
    if tabla.empty:
        return tabla.copy(), float("nan")
    p = min(max(float(percentile), 0.0), 100.0)
    values = pd.to_numeric(tabla[metric_col], errors="coerce").fillna(0.0)
    threshold = float(values.quantile(p / 100.0))
    selected = tabla[values >= threshold].copy()
    selected = selected.sort_values([metric_col, "UITI_VANO_PROM"], ascending=[False, False], kind="stable")
    return selected.reset_index(drop=True), threshold


def _load_mgcecdl_model_and_sigma() -> tuple[Any, float | None]:
    """Load the most recent MGCECDL classifier and resolve its estimated-graph
    `rbf_sigma`, read-only (no train, no Optuna search anywhere in this path).

    Returns `(None, None)` if no model file exists under `DEFAULT_MODEL_DIR`
    (the R3 gap shape -- the caller degrades gracefully rather than raising).
    If the model exists but the Optuna study journal does not, falls back to
    `rbf_sigma=1.0` (existing notebook precedent, cell 34) -- this is NOT the
    R3 gap; the model still loads and the simulator still runs normally.
    """
    try:
        model_path = _modelo_mas_reciente(DEFAULT_MODEL_DIR, DEFAULT_MODEL_BASENAME)
    except FileNotFoundError:
        return None, None

    device = resolve_training_device("auto")
    with warnings.catch_warnings(), redirect_stdout(io.StringIO()):
        warnings.simplefilter("ignore")
        model = cargar_modelo_mgcecdl(str(model_path), device=device)

    try:
        study = cargar_estudio_optuna_mgcecdl(DEFAULT_OPTUNA_STUDY_PATH, "clasificacion")
        rbf_sigma = float(study.best_params.get("rbf_sigma", 1.0))
    except FileNotFoundError:
        rbf_sigma = 1.0

    return model, rbf_sigma


def _persist_scenario_render_assets(
    *,
    scenario_key: str,
    nombre: str,
    resultado: dict[str, Any],
    figures_output_dir: Path,
    render_assets_sink: dict[str, Any],
) -> None:
    """Save one surviving scenario's `fig_barras`/`fig_radar` as PNGs under
    `figures_output_dir` (BEFORE the caller closes them) and record every
    render asset path (figures + the already-persisted `grafo_interactivo`
    HTML) into `render_assets_sink[scenario_key]`.

    Paths are stored ABSOLUTE here -- `_run_inference_simulator` (task 3.2)
    rewrites them relative to `run_dir` afterward, once it knows `run_dir`.
    """
    figures_output_dir.mkdir(parents=True, exist_ok=True)
    fig_barras_path = figures_output_dir / f"{scenario_key}_barras.png"
    fig_radar_path = figures_output_dir / f"{scenario_key}_radar.png"
    resultado["fig_barras"].savefig(fig_barras_path)
    resultado["fig_radar"].savefig(fig_radar_path)

    grafo_path = resultado.get("grafo_interactivo")
    render_assets_sink[scenario_key] = {
        "nombre": nombre,
        "fig_barras_png": str(fig_barras_path),
        "fig_radar_png": str(fig_radar_path),
        "grafo_interactivo_html": str(grafo_path) if grafo_path is not None else None,
    }


@dataclass
class SharedInferenceInputs:
    """Dataset + fitted MinMax scaler computed ONCE per `prepare()` call and
    shared between the inference/SHAP simulator (`_compute_inference_
    scenarios`) and the automatic min/max simulator (`_run_automatic_
    simulator`) (design item 3).

    Before this, both consumers independently recomputed `procesar_dataset_
    completo` and re-fit a MinMax scaler with byte-identical parameters,
    relying on "consistency over DRY" to hope the two recomputes matched.
    Passing one `SharedInferenceInputs` object into both guarantees the
    `feature_scaler` each observes is the SAME object (`is`), not just
    value-equal.

    `datos` is `procesar_dataset_completo`'s result dict; `splits` is
    `escalar_features_minmax_mgcecdl(preparar_splits_estratificados(...))`'s
    result dict (carries `feature_scaler` plus the scaled X splits).
    """

    datos: dict[str, Any]
    splits: dict[str, Any]


def _prepare_shared_inference_inputs(
    source_path: str | Path,
    variables_path: str | Path,
) -> SharedInferenceInputs:
    """Compute `procesar_dataset_completo` + the stratified-split MinMax
    scaler fit EXACTLY ONCE, for `prepare()` to thread into both simulators
    via `shared_inputs` (design item 3).

    Uses the same deterministic parameters `_compute_inference_scenarios`/
    `_run_automatic_simulator` each used to recompute independently
    (`_FILTRO_UITI_MAX`, `_VENTANA_CLIMATICA_HORAS`, `SHAP_RANDOM_STATE`).
    Emits the scaler-refit `warnings.warn` here, at this single shared call
    site, instead of once per consumer.
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

    X_full_raw = np.asarray(datos["X"], dtype=np.float32)
    with redirect_stdout(io.StringIO()):
        splits = escalar_features_minmax_mgcecdl(
            preparar_splits_estratificados(
                X_full_raw,
                datos["y"],
                modo="clasificacion",
                random_state=SHAP_RANDOM_STATE,
            )
        )
    # Same known limitation as the (now-bypassed) per-consumer recompute:
    # this MinMax scaler is re-fit from a fresh stratified split of the
    # CURRENT full CSV, not loaded from a training-time artifact. See
    # `_compute_inference_scenarios`'s own standalone-path comment for the
    # full rationale (unchanged, out of scope here).
    warnings.warn(
        "El escalador MinMax de features se recalcula a partir del dataset "
        "actual en tiempo de reporte, no se carga desde la distribución de "
        "entrenamiento original del modelo. Si el CSV subyacente cambió desde "
        "el entrenamiento, el escalado de entradas puede diverger silenciosamente "
        "de lo que el modelo aprendió.",
        stacklevel=2,
    )
    return SharedInferenceInputs(datos=datos, splits=splits)


def _compute_inference_scenarios(
    circuito: str,
    fecha_inicio: str,
    fecha_fin: str,
    fechas_interes: list[str],
    model: Any,
    rbf_sigma: float,
    *,
    graph_output_dir: str | Path,
    data_path: str | Path | None = None,
    variables_seleccion_path: str | Path | None = None,
    top_n_vanos_percentile: float = _TOP_N_VANOS_PERCENTILE,
    top_k_vars: int = _TOP_K_VARS,
    filtro_uiti_max: float | None = _FILTRO_UITI_MAX,
    ventana_climatica_horas: int = _VENTANA_CLIMATICA_HORAS,
    figures_output_dir: str | Path | None = None,
    render_assets_sink: dict[str, Any] | None = None,
    shared_inputs: SharedInferenceInputs | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Compute `features` (always, once per circuit/window) and up to four
    scenario context dicts (severity/frequency x período completo/fechas de
    interés), skipping any scenario with zero surviving events individually.

    Ports the notebook's cells 32-44 (deprecated in place) into one function.
    `features` is returned even when every scenario is skipped (R1 gap shape,
    obs#219) -- it is computed once, independent of scenario survival. When
    the circuit/window has zero events at all, `features` is still returned
    (computed over the full dataset) but `escenarios` is `[]` without ever
    constructing the SHAP explainer.

    `figures_output_dir`/`render_assets_sink` are additive, optional keyword-
    only parameters (task 3.2): when both are given, each surviving
    scenario's `fig_barras`/`fig_radar` PNGs are saved under
    `figures_output_dir` (ABSOLUTE paths) and recorded into
    `render_assets_sink`, keyed by scenario key
    (`top_uiti_periodo`/`top_frecuencia_periodo`/`top_uiti_puntos_criticos`/
    `top_frecuencia_puntos_criticos`). When omitted (the default), behavior
    is byte-for-byte unchanged from Phase 2 (PR1) -- existing callers/tests
    are unaffected.

    `shared_inputs` (design item 3), when given, reuses its precomputed
    `procesar_dataset_completo` result and fitted `feature_scaler` instead of
    recomputing them here -- this is what guarantees `_run_automatic_
    simulator` observes the identical, object-identical scaler within one
    `prepare()` call. Defaults to `None`, which recomputes internally exactly
    as before (standalone callers, e.g. `tests/test_report_pipeline_inference
    _simulator.py`, are unaffected).
    """
    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    variables_path = (
        Path(variables_seleccion_path)
        if variables_seleccion_path is not None
        else DEFAULT_VARIABLES_SELECCION_PATH
    )

    if shared_inputs is not None:
        datos_inferencia = shared_inputs.datos
    else:
        with redirect_stdout(io.StringIO()):
            datos_inferencia = procesar_dataset_completo(
                path_clima=source_path,
                path_variables_seleccion=variables_path,
                use_sampling=False,
                min_samples_per_codigo=5,
                target="UITI_VANO",
                filtro_uiti_max=filtro_uiti_max,
                ventana_climatica_horas=ventana_climatica_horas,
            )

    features = list(datos_inferencia["features"])
    X_full_raw = np.asarray(datos_inferencia["X"], dtype=np.float32)
    base_full = datos_inferencia["df_original_copy"].copy().reset_index(drop=True)

    # `.floor("D")` (matches `data_loader.filter_events`'s own convention)
    # rather than a raw timestamp compare: `FECHA` carries a time-of-day
    # component, so comparing it directly against date-only `fecha_inicio`/
    # `fecha_fin` strings would silently drop same-day events whose time is
    # after midnight -- the notebook precedent (cell 32) has this same gap,
    # not ported here since it would corrupt the window match.
    fechas_col = pd.to_datetime(base_full["FECHA"], errors="coerce")
    fechas_dia = fechas_col.dt.floor("D")
    mascara = (
        base_full["CIRCUITO"].astype(str).str.strip().eq(circuito)
        & fechas_dia.ge(pd.Timestamp(fecha_inicio))
        & fechas_dia.le(pd.Timestamp(fecha_fin))
    )
    if not mascara.any():
        return features, []

    if model is None:
        # R3 gap: no MGCECDL model was loaded (`_load_mgcecdl_model_and_sigma`
        # returns `(None, None)` when no model artifact exists on disk). Degrade
        # gracefully here -- same `(features, [])` shape as the zero-events gap
        # above -- rather than crashing later inside
        # `KernelShapTopVarsExtractor.__init__`/`_MGCECDLClassifierShapAdapter`
        # with an unguarded `AttributeError: 'NoneType' object has no
        # attribute 'to'` when a SHAP-driving call touches `model.to(device)`.
        return features, []

    if shared_inputs is not None:
        splits = shared_inputs.splits
    else:
        with redirect_stdout(io.StringIO()):
            splits = escalar_features_minmax_mgcecdl(
                preparar_splits_estratificados(
                    X_full_raw,
                    datos_inferencia["y"],
                    modo="clasificacion",
                    random_state=SHAP_RANDOM_STATE,
                )
            )
        # KNOWN LIMITATION (bounded scope): this MinMax scaler is re-fit here
        # from a fresh stratified split of the CURRENT full CSV, not loaded
        # from any artifact persisted alongside the trained model
        # (`cargar_modelo_mgcecdl`'s zip does not currently store scaler
        # stats). If the underlying CSV changes between the model's training
        # time and a later report run, input scaling silently drifts from
        # what the model actually learned. Fixing this properly requires a
        # model-export format change (persisting training-time scaler stats)
        # that is out of scope for this report-only change -- see
        # `_load_mgcecdl_model_and_sigma`'s own read-only contract.
        warnings.warn(
            "El escalador MinMax de features se recalcula a partir del dataset "
            "actual en tiempo de reporte, no se carga desde la distribución de "
            "entrenamiento original del modelo. Si el CSV subyacente cambió desde "
            "el entrenamiento, el escalado de entradas puede diverger silenciosamente "
            "de lo que el modelo aprendió.",
            stacklevel=2,
        )
    feature_scaler = splits["feature_scaler"]
    X_full = feature_scaler.transform(X_full_raw).astype(np.float32)

    mask_np = mascara.to_numpy()
    X_inf = X_full[mask_np]
    base_inf = base_full[mascara].copy().reset_index(drop=True)
    base_inf["_FECHA_DIA"] = fechas_dia[mascara].dt.strftime("%Y-%m-%d").values

    device = resolve_training_device("auto")
    shap_adapter = _MGCECDLClassifierShapAdapter(model, device)
    # `shap.KernelExplainer` samples feature coalitions via the numpy
    # GLOBAL RNG (see comment below), so seeding it here is a process-wide
    # side effect. Save/restore the global state around the SHAP
    # computation so this function never silently resets or correlates
    # unrelated randomness for other code sharing the process afterward
    # (e.g. other circuits processed in the same run).
    rng_state = np.random.get_state()
    try:
        # `KernelShapTopVarsExtractor(random_state=...)` only seeds the LOCAL
        # generator used to draw the SHAP background sample. `shap.KernelExplainer`
        # itself samples feature coalitions via the numpy GLOBAL RNG
        # (`np.random.choice`/`permutation`), so reproducible top-vars rankings
        # across runs also require seeding that global state explicitly here.
        np.random.seed(SHAP_RANDOM_STATE)
        shap_extractor = KernelShapTopVarsExtractor(
            model=shap_adapter,
            X=X_inf,
            features=features,
            top_k=top_k_vars,
            background_size=_SHAP_BACKGROUND_SIZE,
            nsamples=_SHAP_NSAMPLES,
            batch_size=_SHAP_BATCH_SIZE,
            random_state=SHAP_RANDOM_STATE,
        )
        modos = construir_modos_chec(features, variables_path)
        tabla_periodo_inf = agrupar_por_vano(base_inf)

        graph_dir = Path(graph_output_dir)
        try:
            graph_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # A once-per-circuit failure (permission-denied, disk-full,
            # read-only `run_dir` mount, ...) creating the graph-output
            # directory. Every scenario below needs a writable `graph_dir` to
            # pass into `graficar_barras_y_radar` (`graph_output_dir=graph_dir`),
            # so this is a whole-call degrade, not a per-scenario one: match
            # the `model is None` gap shape immediately above this block
            # (`(features, [])`) rather than letting the exception propagate
            # out of `prepare()` and abort the run before scenario 1 even
            # starts.
            warnings.warn(
                "No se pudo crear el directorio de salida de grafos "
                f"'{graph_dir}': {exc}. El simulador de inferencia continúa "
                "sin escenarios ni grafos interactivos para esta ejecución.",
                stacklevel=2,
            )
            return features, []

        def _ejecutar_escenario(
            nombre: str,
            criterio: str,
            tabla_top: pd.DataFrame,
            eventos: pd.DataFrame,
            graph_output_name: str,
            scenario_key: str,
            fechas: list[str] | None = None,
        ) -> dict[str, Any] | None:
            # Snapshot open figure numbers BEFORE calling
            # `graficar_barras_y_radar`, not after: it can raise partway
            # through (e.g. `PermissionError` writing the graph HTML, or a
            # `ValueError` deep inside graph estimation) after creating
            # `fig_barras`/`fig_radar` but before returning, in which case
            # `resultado` is never assigned and those figures would
            # otherwise never be closed.
            fignums_before = set(plt.get_fignums())
            try:
                try:
                    resultado = graficar_barras_y_radar(
                        eventos,
                        nombre,
                        circuito=circuito,
                        features=features,
                        modos=modos,
                        shap_extractor=shap_extractor,
                        top_k=top_k_vars,
                        graph_source="estimated",
                        estimated_graph_model=model,
                        X_model=X_inf,
                        estimated_graph_rbf_sigma=rbf_sigma,
                        estimated_graph_device=device,
                        estimated_graph_batch_size=_SHAP_BATCH_SIZE,
                        graph_output_dir=graph_dir,
                        graph_output_name=graph_output_name,
                    )
                    contexto = construir_contexto_escenario_inferencia(
                        nombre=nombre,
                        criterio=criterio,
                        resultado=resultado,
                        tabla_top=tabla_top,
                        modos=modos,
                        top_k=top_k_vars,
                        fechas_interes=fechas,
                        ventana_climatica_horas=ventana_climatica_horas,
                    )
                except ValueError as exc:
                    # A `ValueError` raised anywhere inside
                    # `graficar_barras_y_radar`/`construir_contexto_escenario_inferencia`
                    # for THIS scenario (e.g.
                    # `construir_grafo_interactivo_muestras`'s "no hay variables
                    # con puntaje positivo para construir el grafo") is a
                    # legitimate per-scenario gap, not a reason to abort the
                    # other scenarios already computed in this same call (R1 gap
                    # shape, obs#219: "a scenario with insufficient signal is
                    # skipped individually; the other scenarios still
                    # complete"). The message is surfaced via `warnings.warn`
                    # (not silently discarded) so a genuine bug is still visible
                    # in logs instead of being indistinguishable from a clean
                    # skip.
                    #
                    # This `except` is scoped ONLY to the computation calls
                    # above -- it must never also catch a `ValueError` raised
                    # by the render-asset persistence step below, or a
                    # file-write problem would be misreported as an
                    # insufficient-signal gap and the already-computed
                    # `contexto` would be discarded even though it is valid.
                    warnings.warn(
                        f"Escenario de inferencia '{nombre}' omitido por ValueError: {exc}",
                        stacklevel=2,
                    )
                    return None
                except OSError as exc:
                    # An `OSError`/`PermissionError` raised while
                    # `graficar_barras_y_radar` -> `mostrar_grafo_interactivo_muestras`
                    # -> `construir_grafo_interactivo_muestras` writes the
                    # interactive graph HTML (`output_path.parent.mkdir(...)` /
                    # `output_path.write_text(...)`) happens BEFORE that call
                    # returns, so neither `resultado` nor `contexto` is ever
                    # built for THIS scenario -- the contexto is not separable
                    # from the graph write in this call chain. Same
                    # per-scenario skip shape as the `ValueError` case above
                    # (this scenario is omitted, the others already computed
                    # in this same call are unaffected), just a distinct
                    # warning message so a disk-write failure is never
                    # confused with an insufficient-signal skip.
                    warnings.warn(
                        f"Escenario de inferencia '{nombre}' omitido: no se pudo "
                        f"escribir el grafo HTML interactivo: {exc}",
                        stacklevel=2,
                    )
                    return None

                if figures_output_dir is not None and render_assets_sink is not None:
                    # Persist PNGs BEFORE the `finally` block below closes the
                    # figures -- once closed, `fig.savefig(...)` would render
                    # a blank image (task 3.2).
                    #
                    # This step has its own narrow error boundary, separate
                    # from the computation `except ValueError`/`except OSError`
                    # above: a persistence-layer failure (`OSError`/
                    # `PermissionError` from `figures_output_dir.mkdir`/
                    # `fig_barras.savefig`/`fig_radar.savefig`, or a
                    # `ValueError` `Figure.savefig` can raise for a
                    # backend/format issue) must never discard the already-
                    # successfully-computed `contexto`, and must never
                    # propagate out of `prepare()` -- per the documented
                    # degrade contract, the run always continues and the
                    # report always generates. The scenario simply ends up
                    # without a `render_assets_sink` entry (same shape
                    # `render()` already tolerates for a scenario missing
                    # from the sidecar).
                    #
                    # NOTE: this boundary does NOT cover the interactive
                    # graph-HTML write (`mostrar_grafo_interactivo_muestras` /
                    # `construir_grafo_interactivo_muestras`'s
                    # `output_path.parent.mkdir(...)` / `.write_text(...)`) --
                    # by the time this line runs, `graficar_barras_y_radar`
                    # has already returned successfully, so that write already
                    # happened earlier and is caught by the `except OSError`
                    # above instead (which skips the whole scenario, since
                    # `contexto` is not separable from that write).
                    try:
                        _persist_scenario_render_assets(
                            scenario_key=scenario_key,
                            nombre=nombre,
                            resultado=resultado,
                            figures_output_dir=Path(figures_output_dir),
                            render_assets_sink=render_assets_sink,
                        )
                    except (OSError, ValueError) as exc:
                        warnings.warn(
                            "No se pudieron persistir los activos de render "
                            f"para el escenario '{nombre}': {exc}",
                            stacklevel=2,
                        )
                return contexto
            finally:
                # `graficar_barras_y_radar` returns open matplotlib Figure
                # objects (`fig_barras`/`fig_radar`) purely as a side effect of
                # plotting -- the JSON context above never references them, so
                # they must be closed here or they leak for the lifetime of the
                # process (observed as "More than 20 figures have been
                # opened"). Diff `plt.get_fignums()` against the snapshot
                # above rather than reading `resultado["fig_barras"]`/
                # `["fig_radar"]`: on the exception path `resultado` may
                # never get assigned at all, so any figure created before the
                # raise would otherwise leak.
                for fignum in set(plt.get_fignums()) - fignums_before:
                    plt.close(fignum)

        escenarios: list[dict[str, Any]] = []
        fechas_label = ", ".join(fechas_interes or [])

        # Scenario 1/4: severity (UITI_VANO_PROM), full period.
        # The cheap "no events" pre-check below stays as-is (nothing to
        # compute). Any *other* `ValueError` `_ejecutar_escenario` can
        # legitimately raise for THIS scenario (e.g. a real SHAP/graph gap)
        # is caught and warned inside `_ejecutar_escenario` itself, which
        # returns `None` in that case -- `escenarios.append` only runs for a
        # non-`None` result so one scenario's failure never discards the
        # others already computed in this same call (R1 gap shape, obs#219).
        tabla_top_uiti, _ = _seleccionar_vanos_por_percentil(
            tabla_periodo_inf, "UITI_VANO_PROM", top_n_vanos_percentile
        )
        ids_top_uiti = tabla_top_uiti["FID_VANO"].tolist()
        base_top_uiti = base_inf[base_inf["FID_VANO"].isin(ids_top_uiti)].copy()
        if not base_top_uiti.empty:
            resultado_escenario = _ejecutar_escenario(
                f"Top P{top_n_vanos_percentile:g} por UITI_VANO — período completo",
                f"seleccionar vanos con UITI_VANO_PROM >= percentil {top_n_vanos_percentile} del período completo",
                tabla_top_uiti,
                base_top_uiti,
                "top_uiti_periodo.html",
                "top_uiti_periodo",
            )
            if resultado_escenario is not None:
                escenarios.append(resultado_escenario)

        # Scenario 2/4: frequency (N_APARICIONES), full period. Same
        # explicit-empty-check and skip-on-`ValueError` rationale as scenario
        # 1/4 above.
        tabla_top_frecuencia, _ = _seleccionar_vanos_por_percentil(
            tabla_periodo_inf, "N_APARICIONES", top_n_vanos_percentile
        )
        ids_top_frecuencia = tabla_top_frecuencia["FID_VANO"].tolist()
        base_top_frecuencia = base_inf[base_inf["FID_VANO"].isin(ids_top_frecuencia)].copy()
        if not base_top_frecuencia.empty:
            resultado_escenario = _ejecutar_escenario(
                f"Top P{top_n_vanos_percentile:g} por frecuencia — período completo",
                f"seleccionar vanos con N_APARICIONES >= percentil {top_n_vanos_percentile} del período completo; "
                "UITI_VANO_PROM solo ordena empates",
                tabla_top_frecuencia,
                base_top_frecuencia,
                "top_frecuencia_periodo.html",
                "top_frecuencia_periodo",
            )
            if resultado_escenario is not None:
                escenarios.append(resultado_escenario)

        # Scenario 3/4: severity (UITI_VANO_PROM), dates of interest. Same
        # explicit-empty-check and skip-on-`ValueError` rationale as scenario
        # 1/4 above; the dates-of-interest filter itself is checked before
        # grouping/selecting too.
        base_fechas_inf = base_inf[base_inf["_FECHA_DIA"].isin(fechas_interes or [])].copy()
        if not base_fechas_inf.empty:
            tabla_fechas_inf = agrupar_por_vano(base_fechas_inf)
            tabla_top_fechas_uiti, _ = _seleccionar_vanos_por_percentil(
                tabla_fechas_inf, "UITI_VANO_PROM", top_n_vanos_percentile
            )
            ids_top_fechas_uiti = tabla_top_fechas_uiti["FID_VANO"].tolist()
            base_top_fechas_uiti = base_fechas_inf[base_fechas_inf["FID_VANO"].isin(ids_top_fechas_uiti)].copy()
            if not base_top_fechas_uiti.empty:
                resultado_escenario = _ejecutar_escenario(
                    f"Top P{top_n_vanos_percentile:g} por UITI_VANO — puntos críticos ({fechas_label})",
                    f"filtrar fechas críticas y seleccionar vanos con UITI_VANO_PROM >= percentil {top_n_vanos_percentile}",
                    tabla_top_fechas_uiti,
                    base_top_fechas_uiti,
                    "top_uiti_fechas.html",
                    "top_uiti_puntos_criticos",
                    fechas=fechas_interes,
                )
                if resultado_escenario is not None:
                    escenarios.append(resultado_escenario)

        # Scenario 4/4: frequency (N_APARICIONES), dates of interest. Same
        # explicit-empty-check and skip-on-`ValueError` rationale as scenario
        # 1/4 above.
        base_fechas_inf = base_inf[base_inf["_FECHA_DIA"].isin(fechas_interes or [])].copy()
        if not base_fechas_inf.empty:
            tabla_fechas_inf = agrupar_por_vano(base_fechas_inf)
            tabla_top_fechas_frecuencia, _ = _seleccionar_vanos_por_percentil(
                tabla_fechas_inf, "N_APARICIONES", top_n_vanos_percentile
            )
            ids_top_fechas_frecuencia = tabla_top_fechas_frecuencia["FID_VANO"].tolist()
            base_top_fechas_frecuencia = base_fechas_inf[
                base_fechas_inf["FID_VANO"].isin(ids_top_fechas_frecuencia)
            ].copy()
            if not base_top_fechas_frecuencia.empty:
                resultado_escenario = _ejecutar_escenario(
                    f"Top P{top_n_vanos_percentile:g} por frecuencia — puntos críticos ({fechas_label})",
                    f"filtrar fechas críticas y seleccionar vanos con N_APARICIONES >= percentil {top_n_vanos_percentile}; "
                    "UITI_VANO_PROM solo ordena empates",
                    tabla_top_fechas_frecuencia,
                    base_top_fechas_frecuencia,
                    "top_frecuencia_fechas.html",
                    "top_frecuencia_puntos_criticos",
                    fechas=fechas_interes,
                )
                if resultado_escenario is not None:
                    escenarios.append(resultado_escenario)

        return features, escenarios
    finally:
        np.random.set_state(rng_state)


def _run_inference_simulator(
    model: Any,
    rbf_sigma: float | None,
    circuito: str,
    fecha_inicio: str,
    fecha_fin: str,
    fechas_interes: list[str],
    run_dir: str | Path,
    *,
    data_path: str | Path | None = None,
    shared_inputs: SharedInferenceInputs | None = None,
) -> tuple[list[str], list[dict[str, Any]], str, float | None, dict[str, Any]]:
    """Orchestrate the read-only MGCECDL/SHAP simulator for one `prepare()`
    run: compute the four scenario contexts (task 2.3) from the already-
    loaded `model`/`rbf_sigma` (hoisted to `prepare()` -- design D2 -- so the
    model is loaded once per run and shared with `_run_automatic_simulator`),
    and persist each surviving scenario's figures under `run_dir` (task 3.2).

    `shared_inputs` (design item 3), when given, is forwarded to
    `_compute_inference_scenarios` so this simulator and `_run_automatic_
    simulator` share the identical dataset/scaler instead of each
    recomputing it. Defaults to `None` (each recomputes internally, current
    behavior unchanged).

    Returns `(features, escenarios, modelo_label, rbf_sigma, render_assets)`.

    `render_assets` maps scenario key
    (`top_uiti_periodo`/`top_frecuencia_periodo`/`top_uiti_puntos_criticos`/
    `top_frecuencia_puntos_criticos`) to
    `{"nombre", "fig_barras_png", "fig_radar_png", "grafo_interactivo_html"}`,
    every path **relative to `run_dir`** (never absolute) so the sidecar
    stays portable if `run_dir` is copied/moved.

    R3 gap (obs#219, structural -- no model artifact on disk): the simulator
    "never runs" -- this function returns immediately WITHOUT calling
    `_compute_inference_scenarios` at all, so `features` stays `[]` too. This
    is intentionally different from `_compute_inference_scenarios`'s own
    `model=None` branch (task 2.3), which still computes `features` as a
    narrower defense-in-depth degrade for callers that invoke it directly
    with `model=None` -- the two are not the same case, and only THIS
    early-return path is the real production R3 shape (features=[]).
    """
    run_dir = Path(run_dir)
    if model is None:
        return [], [], _NO_SIMULATOR_MODEL_LABEL, None, {}

    modelo_label = type(model).__name__
    render_assets: dict[str, Any] = {}
    features, escenarios = _compute_inference_scenarios(
        circuito,
        fecha_inicio,
        fecha_fin,
        fechas_interes,
        model,
        rbf_sigma,
        graph_output_dir=run_dir / "inference_graphs",
        data_path=data_path,
        figures_output_dir=run_dir / "inference_figures",
        render_assets_sink=render_assets,
        shared_inputs=shared_inputs,
    )

    for asset in render_assets.values():
        for field in ("fig_barras_png", "fig_radar_png", "grafo_interactivo_html"):
            value = asset.get(field)
            if value is not None:
                asset[field] = str(Path(value).relative_to(run_dir))

    return features, escenarios, modelo_label, rbf_sigma, render_assets


def _variables_desde_inferencia(inference_context: dict[str, Any] | None) -> list[str]:
    """Collect unique variable names referenced by every scenario's
    `top_variables` in an `inference.bc.json`-shaped context.

    Ports the deprecated notebook's `_variables_desde_inferencia` (cell 59),
    with one correction: the notebook read `item["variable"]`, but the real
    `top_variables` records this codebase actually produces
    (`chec_impacto.interpretability.circuit_analysis._series_to_score_records`,
    used by `construir_contexto_escenario_inferencia`) key each entry as
    `"nombre"`, not `"variable"` -- reading the notebook's stale key name
    here would silently yield zero variables against real data. `"variable"`
    is still checked as a fallback for forward/backward compatibility with
    any other producer of this shape.
    """
    variables: list[str] = []
    escenarios = inference_context.get("escenarios") if isinstance(inference_context, dict) else None
    for escenario in escenarios or []:
        if not isinstance(escenario, dict):
            continue
        for item in escenario.get("top_variables") or []:
            if isinstance(item, dict):
                variable = item.get("nombre") or item.get("variable")
            else:
                variable = item
            text = str(variable or "").strip()
            if text and text not in variables:
                variables.append(text)
    return variables


def _run_automatic_simulator(
    circuito: str,
    fecha_inicio: str,
    fecha_fin: str,
    fechas_interes: list[str],
    run_dir: str | Path,
    model: Any,
    *,
    data_path: str | Path | None = None,
    shared_inputs: SharedInferenceInputs | None = None,
) -> dict[str, Any] | None:
    """Run the automatic min/max sensitivity simulator (design D2) and
    persist its compact agent context (`auto-simulator.bc.json`) plus a
    render-only sidecar (`auto_simulation_assets.json`) under `run_dir`.

    `fechas_interes` is accepted for signature parity with
    `_run_inference_simulator`/future extension -- the ported notebook cell
    (59) never filtered the automatic simulator to dates of interest (only
    the full-period mask), so it is currently unused here.

    `shared_inputs` (design item 3): when given, reuses its precomputed
    `procesar_dataset_completo` result and fitted `feature_scaler` instead of
    independently re-deriving the scaled MGCECDL inputs -- this is what
    GUARANTEES this simulator and `_run_inference_simulator`/`_compute_
    inference_scenarios` observe the identical dataset and the
    object-identical (`is`) scaler within one `prepare()` call, replacing the
    previous "consistency over DRY" hope that two independent recomputes
    with byte-identical parameters would match. Defaults to `None`, which
    recomputes internally exactly as before (standalone callers are
    unaffected). The candidate variable list is still read back from the
    already-persisted `run_dir/inference.bc.json` (written by `prepare()`
    just before this call), since expert-alignment's `variables_a_priorizar`
    -- the notebook's other variable source -- does not exist yet at
    `prepare()` time (D1: expert-alignment runs later, once the
    historical/inference agents have validated their outputs).

    Returns the compact `auto-simulator.bc.json` context dict, or `None`
    (writing no artifacts) when `model is None` (R3 gap, mirrors
    `_run_inference_simulator`) or the circuit/window has zero matching
    events.
    """
    if model is None:
        return None

    run_dir = Path(run_dir)
    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH

    if shared_inputs is not None:
        datos = shared_inputs.datos
    else:
        with redirect_stdout(io.StringIO()):
            datos = procesar_dataset_completo(
                path_clima=source_path,
                path_variables_seleccion=DEFAULT_VARIABLES_SELECCION_PATH,
                use_sampling=False,
                min_samples_per_codigo=5,
                target="UITI_VANO",
                filtro_uiti_max=_FILTRO_UITI_MAX,
                ventana_climatica_horas=_VENTANA_CLIMATICA_HORAS,
            )

    features = list(datos["features"])
    X_full_raw = np.asarray(datos["X"], dtype=np.float32)
    Xdf_full = datos["Xdata"].copy().reset_index(drop=True)
    base_full = datos["df_original_copy"].copy().reset_index(drop=True)
    label_encoders = datos.get("label_encoders", {})
    max_values_imputed = datos.get("max_values_imputed", {})

    fechas_col = pd.to_datetime(base_full["FECHA"], errors="coerce")
    fechas_dia = fechas_col.dt.floor("D")
    mascara = (
        base_full["CIRCUITO"].astype(str).str.strip().eq(circuito)
        & fechas_dia.ge(pd.Timestamp(fecha_inicio))
        & fechas_dia.le(pd.Timestamp(fecha_fin))
    )
    if not mascara.any():
        return None
    mask_np = mascara.to_numpy()

    if shared_inputs is not None:
        splits = shared_inputs.splits
    else:
        with redirect_stdout(io.StringIO()):
            splits = escalar_features_minmax_mgcecdl(
                preparar_splits_estratificados(
                    X_full_raw,
                    datos["y"],
                    modo="clasificacion",
                    random_state=SHAP_RANDOM_STATE,
                )
            )
        # Same known limitation/warning as `_compute_inference_scenarios`:
        # this MinMax scaler is re-fit here from a fresh stratified split of
        # the CURRENT full CSV, not loaded from a training-time artifact.
        warnings.warn(
            "El escalador MinMax de features se recalcula a partir del dataset "
            "actual en tiempo de reporte (simulador automático), no se carga "
            "desde la distribución de entrenamiento original del modelo.",
            stacklevel=2,
        )
    feature_scaler = splits["feature_scaler"]
    X_full = feature_scaler.transform(X_full_raw).astype(np.float32)

    device = resolve_training_device("auto")

    inference_bc_path = run_dir / "inference.bc.json"
    inference_bc = _read_json(inference_bc_path) if inference_bc_path.exists() else {}
    variables_bajo_analisis = _variables_desde_inferencia(inference_bc)
    variables_simulables = [
        variable
        for variable in variables_bajo_analisis
        if variable in features and variable in Xdf_full.columns
    ]

    metadata: dict[str, Any]
    if not variables_simulables:
        metadata = {
            "warnings": [
                "No hay variables bajo análisis con valores originales disponibles "
                "para el simulador automático."
            ]
        }
        simulation_table = pd.DataFrame()
    else:
        simulation_table, metadata = simulate_automatic_minmax_sensitivity(
            model=model,
            X_scaled=X_full,
            X_raw_model=X_full_raw,
            original_feature_df=Xdf_full,
            feature_names=features,
            variables=variables_simulables,
            feature_scaler=feature_scaler,
            predict_fn=predict_classification,
            device=device,
            mask=mask_np,
            label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
            batch_size=_SHAP_BATCH_SIZE,
        )

    softmax_curves: dict[str, Any] = {"variables": [], "metadata": {"warnings": []}}
    vano_risk_df = pd.DataFrame()
    if not simulation_table.empty:
        softmax_curves = simulate_top_softmax_curves(
            model=model,
            X_scaled=X_full,
            X_raw_model=X_full_raw,
            original_feature_df=Xdf_full,
            feature_names=features,
            variables=variables_simulables,
            feature_scaler=feature_scaler,
            predict_fn=predict_classification,
            device=device,
            mask=mask_np,
            automatic_simulation_table=simulation_table,
            label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
            batch_size=_SHAP_BATCH_SIZE,
            max_variables=4,
            max_values=18,
        )
        vano_risk_df, vano_risk_metadata = simulate_suggested_vano_risk(
            model=model,
            X_scaled=X_full,
            X_raw_model=X_full_raw,
            feature_names=features,
            feature_scaler=feature_scaler,
            predict_fn=predict_classification,
            device=device,
            mask=mask_np,
            vano_ids=base_full["FID_VANO"],
            softmax_curves=softmax_curves,
            label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
            batch_size=_SHAP_BATCH_SIZE,
        )
        metadata["riesgo_por_vano"] = vano_risk_metadata

    try:
        cost_items_df = load_cost_items(DEFAULT_COST_ITEMS_PATH)
        cost_context = build_auto_simulation_cost_context(simulation_table, cost_items_df)
    except (FileNotFoundError, ValueError) as exc:
        # Mirrors the notebook's own `try/except` around cost-context
        # assembly (cell 59): a missing/malformed cost-items workbook
        # degrades to "no cost context" rather than aborting the whole
        # simulator stage -- the rest of the compact context is still useful
        # to the agent without it.
        cost_context = {
            "disponible": False,
            "advertencias": [f"No se pudo construir el contexto de costos del simulador automático: {exc}"],
            "coincidencias": [],
        }

    compact_context = {
        "contexto": {
            "circuito": circuito,
            "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
            "modelo": type(model).__name__,
        },
        "metadata": metadata,
        # Empty at this stage: `variables_a_priorizar` (expert-alignment's
        # output) does not exist yet when `prepare()` calls this function --
        # see the docstring above (D1).
        "variables_priorizadas": [],
        "variables_bajo_analisis": variables_bajo_analisis[:30],
        "tabla_simulador_automatico": simulation_table.head(20).to_dict(orient="records"),
        "costos_items_contratos": cost_context,
        "curvas_softmax_top_variables": softmax_curves,
        "contexto_inferencia_resumen": {
            "escenarios": [
                {
                    "nombre": escenario.get("nombre"),
                    "top_variables": (escenario.get("top_variables") or [])[:4],
                    "modos": (escenario.get("modos") or [])[:3],
                }
                for escenario in (inference_bc.get("escenarios") or [])[:4]
                if isinstance(escenario, dict)
            ],
        },
    }

    try:
        save_json_artifact(compact_context, run_dir / "auto-simulator.bc.json")
        save_json_artifact(
            {
                "table": simulation_table.to_dict(orient="records"),
                "vano_risk": vano_risk_df.to_dict(orient="records") if not vano_risk_df.empty else [],
                "cost_context": cost_context,
                "softmax_curves": softmax_curves,
            },
            run_dir / "auto_simulation_assets.json",
        )
    except OSError as exc:
        # Same degrade shape as `prepare()`'s own `inference_render_assets.json`
        # write: a disk-full/permission-revoked failure here must not crash
        # an otherwise fully successful run -- `_build_auto_simulation_kwargs`
        # already tolerates absent sidecar/bc files (R3-shaped "no automatic
        # simulation for this run"), same as `_build_inference_results` does.
        warnings.warn(
            "No se pudieron escribir los artefactos del simulador automático "
            f"para '{circuito}': {exc}. La ejecución continúa sin discusión "
            "automática de sensibilidad para este run.",
            stacklevel=2,
        )

    return compact_context


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
    # Loaded ONCE here and threaded into both simulators (design D2): the
    # inference/SHAP simulator and the automatic min/max simulator each used
    # to load their own copy of the same MGCECDL model.
    model, rbf_sigma = _load_mgcecdl_model_and_sigma()
    # Computed ONCE here and threaded into both simulators (design item 3):
    # `_run_inference_simulator`/`_compute_inference_scenarios` and
    # `_run_automatic_simulator` each used to independently recompute
    # `procesar_dataset_completo` + re-fit the MinMax scaler with
    # byte-identical parameters. Guarded by `model is not None` (mirrors the
    # R3 no-op both simulators already degrade to) so a run with no trained
    # model artifact never pays this cost for nothing.
    shared_inputs = (
        _prepare_shared_inference_inputs(source_path, DEFAULT_VARIABLES_SELECCION_PATH)
        if model is not None
        else None
    )
    features, escenarios, modelo_label, rbf_sigma, render_assets = _run_inference_simulator(
        model,
        rbf_sigma,
        circuito,
        start,
        end,
        fechas_interes,
        run_dir,
        data_path=source_path,
        shared_inputs=shared_inputs,
    )
    inference_context = construir_contexto_inferencia(
        circuito_interes=circuito,
        fecha_inicio=start,
        fecha_fin=end,
        fechas_interes=fechas_interes,
        top_n_vanos=_TOP_N_VANOS_PERCENTILE,
        top_k_vars=_TOP_K_VARS,
        filtro_uiti_max=_FILTRO_UITI_MAX,
        ventana_climatica_horas=_VENTANA_CLIMATICA_HORAS,
        features=features,
        base=events_df,
        escenarios=escenarios,
        modelo=modelo_label,
        estimated_graph_rbf_sigma=rbf_sigma,
        top_vanos_percentile=_TOP_N_VANOS_PERCENTILE,
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
    _run_automatic_simulator(
        circuito,
        start,
        end,
        fechas_interes,
        run_dir,
        model,
        data_path=source_path,
        shared_inputs=shared_inputs,
    )

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


def _build_auto_simulation_kwargs(run_dir: Path) -> dict[str, Any]:
    """Read the optional auto-simulator artifacts under `run_dir` and build
    the 5 `automatic_simulation_*` kwargs `render_llm_analysis` accepts
    (design D3).

    Mirrors `_build_inference_results`'s degrade contract exactly: an absent
    `auto_simulation_assets.json` sidecar or `auto-simulator.out.json`
    (agent analysis, invalid/`ok: false`/missing envelope) simply leaves the
    corresponding kwarg `None` -- never a crash, whether the automatic
    simulator never ran (R3: no model) or its agent step was skipped.
    """
    kwargs: dict[str, Any] = {
        "automatic_simulation_table": None,
        "automatic_simulation_analysis": None,
        "automatic_simulation_cost_context": None,
        "automatic_simulation_softmax_curves": None,
        "automatic_simulation_vano_risk_df": None,
    }

    assets_path = run_dir / "auto_simulation_assets.json"
    if assets_path.exists():
        assets = _read_json(assets_path)
        table_records = assets.get("table")
        vano_risk_records = assets.get("vano_risk")
        kwargs["automatic_simulation_table"] = pd.DataFrame(table_records) if table_records else None
        kwargs["automatic_simulation_vano_risk_df"] = (
            pd.DataFrame(vano_risk_records) if vano_risk_records else None
        )
        kwargs["automatic_simulation_cost_context"] = assets.get("cost_context")
        kwargs["automatic_simulation_softmax_curves"] = assets.get("softmax_curves")

    out_path = run_dir / "auto-simulator.out.json"
    if out_path.exists():
        payload = _read_json(out_path)
        if isinstance(payload, dict) and payload.get("ok") is True and "data" in payload:
            kwargs["automatic_simulation_analysis"] = payload["data"]

    return kwargs


def _detect_llm_runtime() -> tuple[str, str]:
    """Best-effort detection of the orchestrating agent host and its model.

    The report is authored by whichever interactive agent runtime is driving
    this run (Claude Code or OpenCode) -- there is no LLM API call inside
    this module to introspect (see module docstring). The host is
    identifiable from environment variables the CLI sets on its subprocesses;
    the specific orchestrator *model* id is not exposed via any environment
    variable, so it can only come from an explicit override -- the invoking
    agent knows its own identity and is expected to pass `CHEC_LLM_MODEL` (or
    `render(..., llm_model=...)` directly).

    Returns `(provider, model)`, each `"Desconocido"` when undetected.
    """
    provider_override = os.environ.get("CHEC_LLM_PROVIDER", "").strip()
    model_override = os.environ.get("CHEC_LLM_MODEL", "").strip() or "Desconocido"

    if provider_override:
        return provider_override, model_override
    if os.environ.get("CLAUDECODE") == "1" or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        return "Claude Code", model_override
    if any(key.startswith("OPENCODE") for key in os.environ):
        return "OpenCode", model_override
    return "Desconocido", model_override


def _resolve_token_usage(run_dir: Path) -> tuple[int, int, str]:
    """Resolve `(tokens_input, tokens_output, token_source)` for this run's
    agent-authored stages (design item 4), preferring REAL per-stage counts
    from an optional `run_dir/token_usage.json` sidecar over the char/4
    estimate (replaces the estimate-only `_estimate_token_usage`).

    `token_usage.json` (optional -- written by the invoking agent after each
    Skill call whose runtime exposes usage, see `.claude/skills/reporte/
    SKILL.md` steps 3/4/4b/6) maps stage name
    (`"historical"`/`"inference"`/`"auto-simulator"`/`"expert-alignment"`) to
    `{"input": int, "output": int}`. Only stages that actually ran (i.e. have
    a `{stage}.bc.json` and/or a successfully-validated `{stage}.out.json`
    under `run_dir`) are considered; a stage absent from BOTH files
    contributes nothing to either total, same as the old estimate-only
    behavior.

    For any considered stage missing from the sidecar (or missing an
    `"input"`/`"output"` key), falls back to the char/4 estimate for THAT
    stage only -- applied as `characters // 4` (a common rule-of-thumb for
    English/Spanish text) over `*.bc.json` (input proxy) and `*.out.json`'s
    `data` (output proxy), same conservative undercount as before (excludes
    static prompt/playbook text).

    `token_source`:
    - `"measured"`: every considered stage's counts came from the sidecar.
    - `"mixed"`: the sidecar covers some, but not all, considered stages.
    - `"estimated"`: no sidecar (or it covers none of the considered
      stages) -- every count is the char/4 estimate. Also returned (as
      `(0, 0, "estimated")`) when no stage produced any file at all.
    """
    sidecar_path = run_dir / "token_usage.json"
    sidecar = _read_json(sidecar_path) if sidecar_path.exists() else {}
    if not isinstance(sidecar, dict):
        sidecar = {}

    tokens_input = 0
    tokens_output = 0
    estimated_chars_in = 0
    estimated_chars_out = 0
    considered_count = 0
    measured_count = 0

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
        if isinstance(stage_usage, dict) and "input" in stage_usage and "output" in stage_usage:
            tokens_input += int(stage_usage["input"])
            tokens_output += int(stage_usage["output"])
            measured_count += 1
        else:
            estimated_chars_in += chars_in or 0
            estimated_chars_out += chars_out or 0

    tokens_input += estimated_chars_in // 4
    tokens_output += estimated_chars_out // 4

    if considered_count == 0 or measured_count == 0:
        token_source = "estimated"
    elif measured_count == considered_count:
        token_source = "measured"
    else:
        token_source = "mixed"

    return tokens_input, tokens_output, token_source


def render(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
) -> Path:
    """Read all three validated outputs from `run_dir` and render the final
    HTML report via `plotting.render_llm_analysis`.

    Reconstructs `raw_df`/`daily_df` deterministically from `l1_state.json`
    (data_path + circuito + resolved date window) rather than serializing
    DataFrames to disk, so the run_dir stays plain-JSON. `render()` itself
    stays model-free: `inference_results` (task 3.4) is rebuilt purely from
    persisted paths in `inference_render_assets.json`, never by reloading the
    MGCECDL model or recomputing SHAP.

    `llm_provider`/`llm_model` identify, in the report header, which agent
    host and which orchestrator model produced this run. `llm_provider`
    defaults to autodetection (`_detect_llm_runtime`, Claude Code vs
    OpenCode via environment variables); `llm_model` has no reliable
    environment signal and defaults to `"Desconocido"` unless the caller
    passes it explicitly or sets `CHEC_LLM_MODEL`. `tokens_input`/
    `tokens_output` precedence (design item 4): explicit kwargs (both given)
    > real per-stage counts from `run_dir/token_usage.json` (when present)
    > `_resolve_token_usage`'s deterministic, file-size-based char/4
    estimate. The resolved source is labeled `measured`/`mixed`/`estimated`
    in the report header via the `token_source` kwarg passed to
    `render_llm_analysis`.
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
    if tokens_input is None or tokens_output is None:
        # Explicit kwargs (both given) skip resolution entirely -- see
        # branch below. Otherwise, resolve from `run_dir` (sidecar-real >
        # char/4 estimate) and only fill in whichever kwarg was omitted.
        resolved_input, resolved_output, token_source = _resolve_token_usage(run_dir)
        tokens_input = resolved_input if tokens_input is None else tokens_input
        tokens_output = resolved_output if tokens_output is None else tokens_output
    else:
        token_source = "measured"

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
        "token_source": token_source,
        **_build_auto_simulation_kwargs(run_dir),
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
