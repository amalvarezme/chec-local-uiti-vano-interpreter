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

import io
import json
import warnings
from contextlib import redirect_stdout
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
    """
    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    variables_path = (
        Path(variables_seleccion_path)
        if variables_seleccion_path is not None
        else DEFAULT_VARIABLES_SELECCION_PATH
    )

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

    with redirect_stdout(io.StringIO()):
        splits = escalar_features_minmax_mgcecdl(
            preparar_splits_estratificados(
                X_full_raw,
                datos_inferencia["y"],
                modo="clasificacion",
                random_state=SHAP_RANDOM_STATE,
            )
        )
    feature_scaler = splits["feature_scaler"]
    # KNOWN LIMITATION (bounded scope): this MinMax scaler is re-fit here from
    # a fresh stratified split of the CURRENT full CSV, not loaded from any
    # artifact persisted alongside the trained model (`cargar_modelo_mgcecdl`'s
    # zip does not currently store scaler stats). If the underlying CSV
    # changes between the model's training time and a later report run, input
    # scaling silently drifts from what the model actually learned. Fixing
    # this properly requires a model-export format change (persisting
    # training-time scaler stats) that is out of scope for this report-only
    # change -- see `_load_mgcecdl_model_and_sigma`'s own read-only contract.
    warnings.warn(
        "El escalador MinMax de features se recalcula a partir del dataset "
        "actual en tiempo de reporte, no se carga desde la distribución de "
        "entrenamiento original del modelo. Si el CSV subyacente cambió desde "
        "el entrenamiento, el escalado de entradas puede diverger silenciosamente "
        "de lo que el modelo aprendió.",
        stacklevel=2,
    )
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
        graph_dir.mkdir(parents=True, exist_ok=True)

        def _ejecutar_escenario(
            nombre: str,
            criterio: str,
            tabla_top: pd.DataFrame,
            eventos: pd.DataFrame,
            graph_output_name: str,
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
                return construir_contexto_escenario_inferencia(
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
                warnings.warn(
                    f"Escenario de inferencia '{nombre}' omitido por ValueError: {exc}",
                    stacklevel=2,
                )
                return None
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
                    fechas=fechas_interes,
                )
                if resultado_escenario is not None:
                    escenarios.append(resultado_escenario)

        return features, escenarios
    finally:
        np.random.set_state(rng_state)


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
