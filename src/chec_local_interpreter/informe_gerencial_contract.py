"""Shared runtime contract for `/informe-gerencial` -- cross-circuit managerial
report synthesized across a criticality group's most representative circuits.

Sibling of `circuit_clustering_contract.py`/`batch_report_contract.py`: this
module resolves a criticality-group slug (or `todos`) to its full circuit
universe via `compute_circuit_criticality_groups` (reusing
`batch_report_contract`'s `normalize_request`/`GROUP_SLUGS`/
`_dataset_date_range` for argument and date-window resolution ONLY --
`batch_report_contract.preflight_batch`'s own `todos` bypass is NEVER called
or modified here; this module always computes criticality via
`compute_circuit_criticality_groups` for every group including `todos`), then
samples the top-20 most representative circuits (smallest `centroid_distance`
to their assigned cluster centroid), detects any of them missing a prior
`/report` run, and loads their narrative content.

Content sourcing (Phase 3): vault-note-preferred with a raw-JSON fallback is
the DESIGNED end state (`vault_note_contract.find_latest_run` /
`load_run_narratives`, from the sibling `vault-circuito` change). That module
is NOT YET present on this branch (its PRs are open but unmerged), so this
file implements the fallback path -- reading `expert-alignment.out.json`
directly from `reports/interpretability/runs/{canonical_circuit}/` -- as the
PRIMARY path for now. `find_latest_run`/`load_circuit_content` are structured
so that once `vault_note_contract` lands, swapping the local fallback
implementations for the vault-note-preferred ones is a localized, additive
change (same function names/signatures, no call-site churn).
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

import pandas as pd

from chec_local_interpreter.agent_output import ReportPipelineError, load_validated_agent_output
from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text
from chec_local_interpreter.batch_report_contract import (
    ALL_GROUPS_SLUG,
    VALID_GROUP_SLUGS,
)
from chec_local_interpreter.batch_report_contract import normalize_request as _batch_normalize_request
from chec_local_interpreter.circuit_clustering_contract import RuntimeMetadata, _dataset_date_range
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.config import DEFAULT_DATA_PATH, PROJECT_ROOT
from chec_local_interpreter.data_loader import filter_events, load_dataset
from chec_local_interpreter.plotting import (
    compute_circuit_criticality_groups,
    plot_interactive_circuit_clustering,
)

SCHEMA_VERSION = "informe-gerencial-contract/v1"

TOP_N_REPRESENTATIVE = 20

DEFAULT_RUNS_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "runs"
DEFAULT_VAULT_ROOT = PROJECT_ROOT / "reports" / "vault"
DEFAULT_REPORT_OUTPUT_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "html" / "informe-gerencial"

_SAFE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CONTENT_SOURCE_LABELS = {
    "vault_note": "nota de bóveda",
    "raw_json": "JSON crudo (expert-alignment)",
    "sin_contenido": "sin contenido disponible",
}

InformeStatus = Literal[
    "awaiting_confirmation",
    "empty_group",
    "usage_error",
    "execution_error",
    "success",
]


# ---------------------------------------------------------------------------
# Phase 2: sampling + group resolution
# ---------------------------------------------------------------------------


def sample_representatives(df_coords: pd.DataFrame, limit: int = TOP_N_REPRESENTATIVE) -> pd.DataFrame:
    """Select the `limit` most representative circuits (smallest
    `centroid_distance`), deterministically breaking ties by ascending
    circuit id (the frame's index).

    If `df_coords` has `limit` or fewer rows, ALL rows are returned
    unfiltered (spec: "Group under threshold").

    Tie-break mechanism (design decision): `sort_index()` first so that
    `nsmallest`'s default `keep="first"` (which preserves the ORDER rows
    appear in when values tie) resolves ties by ascending circuit id --
    reproducible given `run_kmeans`'s fixed `random_state=42` seeding.
    """
    if len(df_coords) <= limit:
        return df_coords
    return df_coords.sort_index().nsmallest(limit, "centroid_distance")


def resolve_group_dataframe(
    filtered_df: pd.DataFrame, grupo: str, criticidad: str | None
) -> pd.DataFrame:
    """Resolve a criticality-group slug (or `todos`) to its circuit universe.

    Always computes criticality tiers via `compute_circuit_criticality_groups`
    directly -- independent of, and never calling,
    `batch_report_contract.preflight_batch`'s own `todos` bypass (which
    returns raw `available_circuits` instead of clustering results and MUST
    remain unmodified per design/spec non-goals).

    `grupo == "todos"` returns the FULL computed frame (all 5 tiers); any
    named group slug returns only the rows whose `criticidad` matches.
    """
    df_coords = compute_circuit_criticality_groups(filtered_df)
    if grupo == ALL_GROUPS_SLUG:
        return df_coords
    return df_coords[df_coords["criticidad"] == criticidad]


# ---------------------------------------------------------------------------
# Phase 3: missing-run detection + content loading
# ---------------------------------------------------------------------------


def find_latest_run(circuito: str, *, runs_root: str | Path | None = None) -> Path | None:
    """Find the newest run directory for `circuito` that has a validated own
    `expert-alignment.out.json` (a fully completed prior `/report` run).

    Fallback implementation (see module docstring): once
    `vault_note_contract.find_latest_run` exists on this branch, this
    function can delegate to it directly under the same name/signature.

    Never raises -- returns `None` when there is no qualifying prior run,
    the circuit directory doesn't exist, or any entry is unreadable.
    """
    root = Path(runs_root) if runs_root is not None else DEFAULT_RUNS_ROOT
    circuit_dir = root / canonical_circuit_identity(circuito)
    if not circuit_dir.is_dir():
        return None

    qualifying: list[Path] = []
    try:
        candidates = list(circuit_dir.iterdir())
    except OSError:
        return None

    for candidate in candidates:
        try:
            if not candidate.is_dir():
                continue
        except OSError:
            continue
        try:
            load_validated_agent_output(candidate, "expert-alignment")
        except (ReportPipelineError, json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        qualifying.append(candidate)

    if not qualifying:
        return None
    return max(qualifying, key=lambda path: path.name)


def detect_missing_runs(
    sampled_circuitos: Sequence[str], *, runs_root: str | Path | None = None
) -> dict[str, Any]:
    """For each sampled circuit, check `find_latest_run`; return the count
    and names of circuits with no prior `/report` run (spec: "missing-run
    confirmation gate").
    """
    missing = [
        circuito
        for circuito in sampled_circuitos
        if find_latest_run(circuito, runs_root=runs_root) is None
    ]
    return {"count": len(missing), "circuitos": missing}


def load_circuit_content(
    circuito: str,
    *,
    runs_root: str | Path | None = None,
    vault_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load narrative content for `circuito`: vault note preferred, raw JSON
    run artifact as fallback (spec: "Content sourcing").

    Vault-note path is NOT YET implemented against a real
    `vault_note_contract` module (unmerged on this branch, see module
    docstring) -- `reports/vault/{canonical}.md` is still checked first so
    the preference order matches the design once that module lands, but for
    now the raw-JSON fallback is this function's only working source.
    Returns `None` when neither a vault note nor a prior run exists.
    """
    vroot = Path(vault_root) if vault_root is not None else DEFAULT_VAULT_ROOT
    canonical = canonical_circuit_identity(circuito)
    vault_path = vroot / f"{canonical}.md"
    if vault_path.is_file():
        return {
            "circuito": circuito,
            "source": "vault_note",
            "content": vault_path.read_text(encoding="utf-8"),
        }

    run_dir = find_latest_run(circuito, runs_root=runs_root)
    if run_dir is None:
        return None
    data = load_validated_agent_output(run_dir, "expert-alignment")
    return {
        "circuito": circuito,
        "source": "raw_json",
        "run_dir": str(run_dir),
        "content": data.get("sintesis_final", ""),
    }


# ---------------------------------------------------------------------------
# Phase 4: request/outcome contract + resolve() + CLI
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InformeGerencialRequest:
    grupo: str
    criticidad: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    runtime: RuntimeMetadata = field(default_factory=RuntimeMetadata)

    def to_json(self) -> dict[str, Any]:
        return {
            "grupo": self.grupo,
            "criticidad": self.criticidad,
            "fecha_inicio": self.fecha_inicio,
            "fecha_fin": self.fecha_fin,
            "runtime": self.runtime.to_json(),
        }


@dataclass(frozen=True)
class InformeGerencialOutcome:
    status: InformeStatus
    request: InformeGerencialRequest | None = None
    resolved_window: dict[str, Any] | None = None
    group: dict[str, Any] | None = None
    sampled: list[str] = field(default_factory=list)
    missing_runs: dict[str, Any] | None = None
    next_actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output_html: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "request": self.request.to_json() if self.request else None,
            "resolved_window": self.resolved_window,
            "group": self.group,
            "sampled": list(self.sampled),
            "missing_runs": self.missing_runs,
            "next_actions": list(self.next_actions),
            "errors": list(self.errors),
            "output_html": self.output_html if self.status == "success" else None,
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)


def normalize_request(
    grupo: str,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    *,
    runtime: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> InformeGerencialRequest:
    """Validate/normalize CLI-shaped arguments into an
    `InformeGerencialRequest`.

    Reuses `batch_report_contract.normalize_request` for the identical
    `grupo`/`fecha_inicio`/`fecha_fin` validation shape (allowlisted
    `VALID_GROUP_SLUGS`, paired-dates rule) so the two contracts can never
    drift on what a valid `grupo`/date pair looks like -- then repackages the
    result into this module's own request type (spec: "Argument contract").
    """
    batch_request = _batch_normalize_request(
        grupo, fecha_inicio, fecha_fin, runtime=runtime, provider=provider, model=model
    )
    return InformeGerencialRequest(
        grupo=batch_request.grupo,
        criticidad=batch_request.criticidad,
        fecha_inicio=batch_request.fecha_inicio,
        fecha_fin=batch_request.fecha_fin,
        runtime=batch_request.runtime,
    )


def usage_error(message: str, request: InformeGerencialRequest | None = None) -> InformeGerencialOutcome:
    return InformeGerencialOutcome(status="usage_error", request=request, errors=[message])


def _safe_report_filename(*, grupo: str, fecha_inicio: str, fecha_fin: str, suffix: str) -> str:
    """Build a report filename from allowlisted, format-validated inputs
    only -- forecloses path traversal via `grupo`/date values ending up in
    the filename (threat matrix: report HTML filename path injection).
    """
    if grupo not in VALID_GROUP_SLUGS:
        raise ValueError(f"grupo desconocido: {grupo!r}. Opciones: {', '.join(VALID_GROUP_SLUGS)}")
    if not _SAFE_DATE_RE.match(fecha_inicio) or not _SAFE_DATE_RE.match(fecha_fin):
        raise ValueError("fecha_inicio/fecha_fin must be ISO dates (YYYY-MM-DD)")
    return f"informe-gerencial__{grupo}__{fecha_inicio}__{fecha_fin}{suffix}"


def resolve(
    request: InformeGerencialRequest,
    *,
    data_path: str | Path | None = None,
    runs_root: str | Path | None = None,
) -> InformeGerencialOutcome:
    """Resolve a request end to end: dataset load -> date window -> group
    criticality/sampling -> missing-run detection -> status matrix.

    Never raises: wraps `FileNotFoundError`/`ValueError`/`ReportPipelineError`
    into `execution_error`, mirroring `batch_report_contract.preflight_batch`
    and `circuit_clustering_contract.preflight_clustering`'s established
    try/except shape.

    Does NOT load circuit content -- `load_circuit_content` (Phase 3) is
    invoked per sampled circuit by the SKILL runbook's synthesis step
    (Phase 5, PR2), after this gate's confirmation, so it accepts its own
    `vault_root` there rather than threading an unused parameter through
    here.
    """
    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    try:
        frame = load_dataset(source_path)

        if request.fecha_inicio is None:
            fecha_inicio, fecha_fin = _dataset_date_range(frame)
        else:
            fecha_inicio, fecha_fin = request.fecha_inicio, request.fecha_fin

        if fecha_inicio is None or fecha_fin is None:
            raise ValueError("Dataset does not contain any valid FECHA values")

        filtered = filter_events(frame, start_date=fecha_inicio, end_date=fecha_fin)
        if filtered.empty:
            raise ValueError(f"No events found in window {fecha_inicio!r}..{fecha_fin!r}")

        df_group = resolve_group_dataframe(filtered, request.grupo, request.criticidad)
    except (FileNotFoundError, ValueError, ReportPipelineError) as exc:
        return InformeGerencialOutcome(status="execution_error", request=request, errors=[str(exc)])

    resolved_window = {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin}
    group = {
        "slug": request.grupo,
        "label": request.criticidad,
        "circuit_count": int(len(df_group)),
    }

    if df_group.empty:
        return InformeGerencialOutcome(
            status="empty_group",
            request=request,
            resolved_window=resolved_window,
            group=group,
        )

    sampled_df = sample_representatives(df_group)
    sampled = list(sampled_df.index)
    missing_runs = detect_missing_runs(sampled, runs_root=runs_root)

    next_actions = ["confirm_and_trigger_missing"] if missing_runs["count"] > 0 else ["confirm"]

    return InformeGerencialOutcome(
        status="awaiting_confirmation",
        request=request,
        resolved_window=resolved_window,
        group=group,
        sampled=sampled,
        missing_runs=missing_runs,
        next_actions=next_actions,
    )


# ---------------------------------------------------------------------------
# Phase 5: cross-circuit synthesis + HTML render
# ---------------------------------------------------------------------------


def _compute_outliers(sampled_records: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    """Flag circuits whose numeric profile deviates sharply from the sampled
    group's own median -- a genuine cross-circuit comparison, not a
    per-circuit threshold (spec: "notable outliers").

    Uses the group's own median (robust to small samples/skew) rather than
    mean+stdev: with <=20 samples a single extreme value drags mean/stdev
    enough that a mean-based threshold can fail to flag the very outlier it
    is meant to catch. Requires at least 3 sampled circuits -- "outlier"
    relative to a group of 1-2 is not a meaningful signal.
    """
    if len(sampled_records) < 3:
        return []

    uiti_median = statistics.median(r["uiti_vano_sum"] for r in sampled_records)
    event_median = statistics.median(r["event_count"] for r in sampled_records)

    outliers: list[dict[str, str]] = []
    for record in sampled_records:
        reasons: list[str] = []
        if uiti_median > 0 and record["uiti_vano_sum"] > 2 * uiti_median:
            reasons.append(
                f"UITI_VANO acumulado ({record['uiti_vano_sum']:,.2f}) más del doble de la "
                f"mediana del grupo muestreado ({uiti_median:,.2f})"
            )
        if event_median > 0 and record["event_count"] < 0.5 * event_median:
            reasons.append(
                f"frecuencia de eventos ({record['event_count']:,.0f}) muy por debajo de la "
                f"mediana del grupo muestreado ({event_median:,.1f})"
            )
        if reasons:
            outliers.append({"circuito": record["circuito"], "motivo": "; ".join(reasons)})
    return outliers


def _common_patterns(
    sampled_records: Sequence[dict[str, Any]], loaded_content: Sequence[dict[str, Any] | None]
) -> list[str]:
    """Cross-circuit patterns derived from the sampled group's own
    distribution -- criticality-tier mix and narrative-content source mix.
    """
    patterns: list[str] = []

    tier_counts = Counter(record["criticidad"] for record in sampled_records if record.get("criticidad"))
    if tier_counts:
        tier_summary = ", ".join(f"{label} ({count})" for label, count in tier_counts.most_common())
        patterns.append(f"Distribución de criticidad en la muestra: {tier_summary}.")

    source_counts = Counter(
        (content.get("source") if content else "sin_contenido") for content in loaded_content
    )
    if source_counts:
        source_summary = ", ".join(
            f"{_CONTENT_SOURCE_LABELS.get(source, source)} ({count})"
            for source, count in source_counts.most_common()
        )
        patterns.append(f"Origen del contenido narrativo: {source_summary}.")

    return patterns


def _aggregate_risk(
    sampled_records: Sequence[dict[str, Any]],
    loaded_content: Sequence[dict[str, Any] | None],
    group: dict[str, Any],
) -> dict[str, Any]:
    uiti_values = [record["uiti_vano_sum"] for record in sampled_records]
    event_values = [record["event_count"] for record in sampled_records]
    total_uiti = sum(uiti_values)
    n = len(sampled_records)
    avg_uiti = total_uiti / n if n else 0.0
    avg_events = sum(event_values) / n if n else 0.0
    missing_count = sum(1 for content in loaded_content if content is None)

    label = group.get("label") or group.get("slug") or "grupo"
    resumen = (
        f"El grupo '{label}' acumula {total_uiti:,.2f} unidades de UITI_VANO entre {n} "
        f"circuitos representativos, con un promedio de {avg_uiti:,.2f} por circuito y "
        f"{avg_events:,.1f} eventos promedio por circuito."
    )
    return {
        "uiti_vano_total": total_uiti,
        "uiti_vano_promedio": avg_uiti,
        "eventos_promedio": avg_events,
        "circuitos_sin_contenido": missing_count,
        "resumen": resumen,
    }


def _recommended_actions(
    outliers: Sequence[dict[str, str]], missing_circuitos: Sequence[str], group: dict[str, Any]
) -> list[str]:
    label = group.get("label") or group.get("slug") or "grupo"
    actions = [f"Mantener monitoreo periódico del grupo '{label}' mediante /reporte-lote."]
    if outliers:
        names = ", ".join(item["circuito"] for item in outliers)
        actions.append(f"Priorizar inspección técnica en los circuitos atípicos: {names}.")
    if missing_circuitos:
        names = ", ".join(missing_circuitos)
        actions.append(f"Completar la generación de reportes individuales para: {names}.")
    return actions


def _annex_per_circuit(
    sampled_records: Sequence[dict[str, Any]], loaded_content: Sequence[dict[str, Any] | None]
) -> list[dict[str, Any]]:
    annex: list[dict[str, Any]] = []
    for record, content in zip(sampled_records, loaded_content):
        if content is None:
            fuente, extracto = "sin_contenido", "Sin contenido disponible."
        else:
            fuente = content.get("source", "desconocido")
            text = str(content.get("content", "")).strip()
            extracto = f"{text[:220]}…" if len(text) > 220 else text
        annex.append(
            {
                "circuito": record["circuito"],
                "criticidad": record.get("criticidad"),
                "fuente": fuente,
                "extracto": extracto,
            }
        )
    return annex


def _executive_summary(
    sampled_records: Sequence[dict[str, Any]], group: dict[str, Any], outliers: Sequence[dict[str, str]]
) -> str:
    label = group.get("label") or group.get("slug") or "grupo"
    n = len(sampled_records)
    universe = group.get("circuit_count", n)
    return (
        f"Informe gerencial del grupo '{label}': se analizaron {n} circuitos representativos "
        f"de un universo de {universe} en la ventana evaluada. Se identificaron "
        f"{len(outliers)} circuito(s) atípico(s) que requieren atención prioritaria."
    )


def synthesize(
    sampled_records: Sequence[dict[str, Any]],
    loaded_content: Sequence[dict[str, Any] | None],
    group: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the cross-circuit synthesis sections (spec: "Report
    structure") from the sampled circuits' numeric profile
    (`sampled_records`, one dict per circuit with `event_count`,
    `uiti_vano_sum`, `criticidad`) and their loaded narrative content
    (`loaded_content`, same order, `None` where content is unavailable).

    Pure Python, no LLM call -- aggregates/derives from data already produced
    upstream (K-Means criticality + sampling, per-circuit `/report` runs).
    """
    outliers = _compute_outliers(sampled_records)
    missing_circuitos = [
        record["circuito"]
        for record, content in zip(sampled_records, loaded_content)
        if content is None
    ]
    return {
        "resumen_ejecutivo": _executive_summary(sampled_records, group, outliers),
        "patrones_comunes": _common_patterns(sampled_records, loaded_content),
        "circuitos_atipicos": outliers,
        "riesgo_agregado": _aggregate_risk(sampled_records, loaded_content, group),
        "acciones_recomendadas": _recommended_actions(outliers, missing_circuitos, group),
        "anexo_por_circuito": _annex_per_circuit(sampled_records, loaded_content),
    }


def _escape(value: Any) -> str:
    return html_lib.escape("" if value is None else str(value))


def _list_html(items: Sequence[str]) -> str:
    if not items:
        return "<p class='muted'>Sin hallazgos.</p>"
    return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in items) + "</ul>"


def _outliers_html(outliers: Sequence[dict[str, str]]) -> str:
    if not outliers:
        return "<p class='muted'>No se detectaron circuitos atípicos en la muestra.</p>"
    rows = "".join(
        f"<li><strong>{_escape(item['circuito'])}</strong>: {_escape(item['motivo'])}</li>" for item in outliers
    )
    return f"<ul>{rows}</ul>"


def _annex_html(annex: Sequence[dict[str, Any]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_escape(entry['circuito'])}</td>"
        f"<td>{_escape(entry.get('criticidad'))}</td>"
        f"<td>{_escape(_CONTENT_SOURCE_LABELS.get(entry['fuente'], entry['fuente']))}</td>"
        f"<td>{_escape(entry['extracto'])}</td>"
        "</tr>"
        for entry in annex
    )
    return (
        "<table class='annex-table'><thead><tr>"
        "<th>Circuito</th><th>Criticidad</th><th>Fuente</th><th>Extracto</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


_REPORT_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 0 24px 48px; color: #0f172a; background: #f8fafc; }
h1 { font-size: 1.6rem; margin-top: 24px; }
h2 { font-size: 1.2rem; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; }
.meta { color: #475569; }
.report-section { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin: 16px 0; }
.muted { color: #94a3b8; font-style: italic; }
.annex-table { width: 100%; border-collapse: collapse; }
.annex-table th, .annex-table td { border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; font-size: 0.9rem; vertical-align: top; }
"""


def render_managerial_report(
    raw_df: pd.DataFrame,
    *,
    synthesis: dict[str, Any],
    group: dict[str, Any],
    resolved_window: dict[str, Any],
    sampled: Sequence[str],
) -> str:
    """Render the single standalone HTML report (spec: "Single HTML output
    per invocation") -- resumen/patrones/outliers/riesgo/acciones sections
    plus one embedded full-fleet clustering scatter with only `sampled`
    highlighted.

    The scatter reuses `plot_interactive_circuit_clustering(raw_df, ...)`
    AS-IS against the FULL, unfiltered `raw_df` (design decision: "always
    shows all 5 criticality tiers with only the current report's sampled
    circuits highlighted, nothing hidden") and embeds it with the SAME
    `to_html(full_html=False, include_plotlyjs='cdn')` idiom already used by
    `plotting.render_llm_analysis` for the per-circuit report.
    """
    fig = plot_interactive_circuit_clustering(
        raw_df,
        resolved_window.get("fecha_inicio"),
        resolved_window.get("fecha_fin"),
        highlighted_circuits=list(sampled),
    )
    scatter_html = fig.to_html(full_html=False, include_plotlyjs="cdn") if fig else ""

    label = group.get("label") or group.get("slug") or "grupo"
    circuit_count = group.get("circuit_count", len(sampled))

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe Gerencial - {_escape(label)}</title>
<style>{_REPORT_CSS}</style>
</head>
<body>
<h1>Informe Gerencial: {_escape(label)}</h1>
<p class="meta">Ventana: {_escape(resolved_window.get('fecha_inicio'))} a {_escape(resolved_window.get('fecha_fin'))}
&middot; Circuitos muestreados: {len(sampled)} de {circuit_count}</p>

<section class="report-section">
<h2>Resumen ejecutivo del grupo</h2>
<p>{_escape(synthesis['resumen_ejecutivo'])}</p>
</section>

<section class="report-section">
<h2>Patrones comunes</h2>
{_list_html(synthesis['patrones_comunes'])}
</section>

<section class="report-section">
<h2>Circuitos atípicos (outliers)</h2>
{_outliers_html(synthesis['circuitos_atipicos'])}
</section>

<section class="report-section">
<h2>Riesgo agregado</h2>
<p>{_escape(synthesis['riesgo_agregado']['resumen'])}</p>
</section>

<section class="report-section">
<h2>Acciones recomendadas</h2>
{_list_html(synthesis['acciones_recomendadas'])}
</section>

<section class="report-section">
<h2>Mapa de agrupamiento (flota completa, muestra destacada)</h2>
{scatter_html}
</section>

<section class="report-section">
<h2>Anexo por circuito</h2>
{_annex_html(synthesis['anexo_por_circuito'])}
</section>

</body>
</html>"""


def render_and_write(
    request: InformeGerencialRequest,
    *,
    data_path: str | Path | None = None,
    runs_root: str | Path | None = None,
    vault_root: str | Path | None = None,
    output_root: str | Path | None = None,
) -> InformeGerencialOutcome:
    """Full render pipeline: re-resolve the SAME deterministic group/window/
    sampling as `resolve()` (K-Means is seeded, so the sampled set is
    reproducible), load each sampled circuit's content, synthesize, render,
    and persist the HTML report.

    Called by the SKILL runbook's final step, AFTER the confirmation gate has
    cleared and any missing `/report` runs have already been auto-triggered
    (Phase 6) -- this function does not itself gate on missing runs.
    """
    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    try:
        frame = load_dataset(source_path)

        if request.fecha_inicio is None:
            fecha_inicio, fecha_fin = _dataset_date_range(frame)
        else:
            fecha_inicio, fecha_fin = request.fecha_inicio, request.fecha_fin

        if fecha_inicio is None or fecha_fin is None:
            raise ValueError("Dataset does not contain any valid FECHA values")

        filtered = filter_events(frame, start_date=fecha_inicio, end_date=fecha_fin)
        if filtered.empty:
            raise ValueError(f"No events found in window {fecha_inicio!r}..{fecha_fin!r}")

        df_group = resolve_group_dataframe(filtered, request.grupo, request.criticidad)
    except (FileNotFoundError, ValueError, ReportPipelineError) as exc:
        return InformeGerencialOutcome(status="execution_error", request=request, errors=[str(exc)])

    resolved_window = {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin}
    group = {
        "slug": request.grupo,
        "label": request.criticidad,
        "circuit_count": int(len(df_group)),
    }

    if df_group.empty:
        return InformeGerencialOutcome(
            status="empty_group", request=request, resolved_window=resolved_window, group=group
        )

    sampled_df = sample_representatives(df_group)
    sampled_records = [
        {
            "circuito": circuito,
            "event_count": float(row["event_count"]),
            "uiti_vano_sum": float(row["uiti_vano_sum"]),
            "criticidad": row["criticidad"],
            "centroid_distance": float(row["centroid_distance"]),
        }
        for circuito, row in sampled_df.iterrows()
    ]
    sampled = [record["circuito"] for record in sampled_records]

    loaded_content = [
        load_circuit_content(circuito, runs_root=runs_root, vault_root=vault_root) for circuito in sampled
    ]

    synthesis = synthesize(sampled_records, loaded_content, group)
    html = render_managerial_report(
        frame,
        synthesis=synthesis,
        group=group,
        resolved_window=resolved_window,
        sampled=sampled,
    )

    try:
        filename = _safe_report_filename(
            grupo=request.grupo, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, suffix=".html"
        )
        target_root = Path(output_root) if output_root is not None else DEFAULT_REPORT_OUTPUT_ROOT
        target = target_root / filename
        atomic_write_text(target, html)
    except (ValueError, OSError) as exc:
        return InformeGerencialOutcome(
            status="execution_error",
            request=request,
            resolved_window=resolved_window,
            group=group,
            sampled=sampled,
            errors=[str(exc)],
        )

    return InformeGerencialOutcome(
        status="success",
        request=request,
        resolved_window=resolved_window,
        group=group,
        sampled=sampled,
        output_html=str(target),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m chec_local_interpreter.informe_gerencial_contract"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_request_args(command: argparse.ArgumentParser) -> None:
        command.add_argument("grupo")
        command.add_argument("fecha_inicio", nargs="?")
        command.add_argument("fecha_fin", nargs="?")
        command.add_argument("--runtime")
        command.add_argument("--provider")
        command.add_argument("--model")

    parse_command = subparsers.add_parser("parse")
    add_request_args(parse_command)

    resolve_command = subparsers.add_parser("resolve")
    add_request_args(resolve_command)
    resolve_command.add_argument("--data-path")
    resolve_command.add_argument("--runs-root")

    render_command = subparsers.add_parser("render")
    add_request_args(render_command)
    render_command.add_argument("--data-path")
    render_command.add_argument("--runs-root")
    render_command.add_argument("--vault-root")
    render_command.add_argument("--output-root")

    return parser


def _request_from_args(args: argparse.Namespace) -> InformeGerencialRequest:
    return normalize_request(
        args.grupo,
        args.fecha_inicio,
        args.fecha_fin,
        runtime=args.runtime,
        provider=args.provider,
        model=args.model,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        request = _request_from_args(args)
    except ValueError as exc:
        print(usage_error(str(exc)).to_json_text())
        return 2

    if args.command == "parse":
        print(
            InformeGerencialOutcome(
                status="awaiting_confirmation",
                request=request,
                next_actions=["confirm"],
            ).to_json_text()
        )
        return 0
    if args.command == "resolve":
        outcome = resolve(
            request,
            data_path=args.data_path,
            runs_root=args.runs_root,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status == "awaiting_confirmation" else 2
    if args.command == "render":
        outcome = render_and_write(
            request,
            data_path=args.data_path,
            runs_root=args.runs_root,
            vault_root=args.vault_root,
            output_root=args.output_root,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status == "success" else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
