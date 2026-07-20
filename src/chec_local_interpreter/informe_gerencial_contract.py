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
samples the top-12 most representative circuits (smallest `centroid_distance`
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

TOP_N_REPRESENTATIVE = 12

DEFAULT_RUNS_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "runs"
DEFAULT_VAULT_ROOT = PROJECT_ROOT / "reports" / "vault"
DEFAULT_REPORT_OUTPUT_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "html" / "informe-gerencial"
# Mirrors `plotting.render_llm_analysis`'s own default `output_dir` -- the root
# where every per-circuit `/report` HTML lands. This is the ONLY "file" this
# module is allowed to cite to the user (never the internal JSON/markdown run
# artifacts); see `_circuit_report_html_path`.
DEFAULT_CIRCUIT_HTML_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "html"

# Deterministic, non-LLM keyword buckets used to mine shared causal themes
# from each circuit's own `cause_hypothesis_note` (historical agent output).
# Substring matches only -- no inference, no invented causes -- just
# cross-circuit tallying of themes the historical agent already wrote.
_CAUSE_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fauna": ("fauna", "animal"),
    "conductor/vegetación": ("conductor", "vegetaci", "árbol", "arbol", "rama"),
    "clima/atmosférico": ("atmosf", "clima", "viento", "lluvia", "precipita", "ráfaga", "rafaga"),
    "protección/maniobra": ("protecci", "maniobra", "transformador"),
    "topológico/recurrencia de vanos": ("topológic", "topologic", "recurrent", "vano"),
}

_SAFE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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


def _circuit_report_html_path(run_dir: Path, *, html_root: str | Path | None = None) -> str | None:
    """Return the path to `run_dir`'s own rendered `/report` HTML, if it
    exists on disk -- the only "file" this module is ever allowed to cite to
    the user (never the internal JSON/markdown run artifacts a run_dir or
    vault note holds).

    Mirrors the filename convention `report_pipeline._render_output_filename`
    establishes (`{circuito}_{fecha_inicio}_{fecha_fin}_{run_id}.html`),
    reading `run_dir/l1_state.json` back rather than importing that private
    helper. Never raises -- returns `None` on any missing/malformed state or
    a report that was never actually rendered.
    """
    root = Path(html_root) if html_root is not None else DEFAULT_CIRCUIT_HTML_ROOT
    state_path = run_dir / "l1_state.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    circuito = state.get("circuito")
    fecha_inicio = state.get("fecha_inicio")
    fecha_fin = state.get("fecha_fin")
    if not circuito or not fecha_inicio or not fecha_fin:
        return None
    filename = (
        f"{circuito}_{str(fecha_inicio).replace('-', '')}_"
        f"{str(fecha_fin).replace('-', '')}_{run_dir.name}.html"
    )
    candidate = root / filename
    return str(candidate) if candidate.is_file() else None


_VAULT_CAUSE_HYPOTHESIS_RE = re.compile(
    r"^###\s*Hip[óo]tesis de causa\s*\n(.*?)(?=\n#{1,6}\s|\Z)",
    re.DOTALL | re.MULTILINE,
)


def _cause_hypothesis_from_note(note_text: str) -> str | None:
    """Recover ONLY `cause_hypothesis_note` from a vault note's own
    `### Hipótesis de causa` markdown section -- the sole structured field
    verified to survive verbatim in the note (see module docstring/design:
    `variable_groups_used`/`variables_a_priorizar` are never written to the
    note, so they cannot be recovered this way). Never raises -- returns
    `None` when the section is absent or empty.
    """
    match = _VAULT_CAUSE_HYPOTHESIS_RE.search(note_text)
    if not match:
        return None
    text = match.group(1).strip()
    return text or None


def _structured_fields(run_dir: Path) -> dict[str, Any]:
    """Extract `variables_a_priorizar` (expert-alignment) and
    `cause_hypothesis_note`/`variable_groups_used`/`recommended_actions`
    (historical) from `run_dir`'s own JSON artifacts -- the authoritative
    source already on disk, shared by BOTH the vault-note and raw-JSON
    branches of `load_circuit_content` (bugfix: the vault branch previously
    hardcoded these to `None`/`[]` instead of reusing this same extraction).
    Never raises -- degrades to empty defaults on any missing/invalid data.
    """
    try:
        expert_data = load_validated_agent_output(run_dir, "expert-alignment")
    except (ReportPipelineError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        expert_data = None

    variables_a_priorizar = [
        {"variable": item.get("variable"), "prioridad": item.get("prioridad")}
        for item in ((expert_data or {}).get("variables_a_priorizar") or [])
        if item.get("variable")
    ]

    cause_hypothesis_note: str | None = None
    variable_groups_used: list[str] = []
    recommended_actions: list[str] = []
    try:
        historical_data = load_validated_agent_output(run_dir, "historical")
    except (ReportPipelineError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        historical_data = None
    if historical_data:
        cause_hypothesis_note = historical_data.get("cause_hypothesis_note")
        recommended_actions = list(historical_data.get("recommended_actions") or [])
        for finding in historical_data.get("key_findings") or []:
            variable_groups_used.extend(finding.get("variable_groups_used") or [])

    return {
        "cause_hypothesis_note": cause_hypothesis_note,
        "variable_groups_used": variable_groups_used,
        "variables_a_priorizar": variables_a_priorizar,
        "recommended_actions": recommended_actions,
    }


def load_circuit_content(
    circuito: str,
    *,
    runs_root: str | Path | None = None,
    vault_root: str | Path | None = None,
    html_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load narrative content for `circuito`: vault note preferred, raw JSON
    run artifact as fallback (spec: "Content sourcing").

    Vault-note path is NOT YET implemented against a real
    `vault_note_contract` module (unmerged on this branch, see module
    docstring) -- `reports/vault/{canonical}.md` is still checked first so
    the preference order matches the design once that module lands, but for
    now the raw-JSON fallback is this function's only working source.
    Returns `None` when neither a vault note nor a prior run exists.

    Beyond the base `circuito`/`source`/`content` shape, the raw-JSON path
    also surfaces the richer technical signal already produced upstream by
    the per-circuit `/report` run -- `report_html` (the ONLY file citable to
    the user), `variables_a_priorizar` (expert-alignment), and
    `cause_hypothesis_note`/`variable_groups_used`/`recommended_actions`
    (historical) -- so `synthesize()` can build technical, non-descriptive
    cross-circuit sections instead of re-deriving this from scratch. The
    vault-note branch cannot yet populate these (unmerged module, see
    above), so it degrades to empty/`None` for them.
    """
    vroot = Path(vault_root) if vault_root is not None else DEFAULT_VAULT_ROOT
    canonical = canonical_circuit_identity(circuito)
    vault_path = vroot / f"{canonical}.md"

    run_dir = find_latest_run(circuito, runs_root=runs_root)
    report_html = _circuit_report_html_path(run_dir, html_root=html_root) if run_dir is not None else None

    if vault_path.is_file():
        note_text = vault_path.read_text(encoding="utf-8")
        if run_dir is not None:
            structured = _structured_fields(run_dir)
        else:
            # No prior run resolvable -- only `cause_hypothesis_note` can be
            # recovered, parsed directly from the note's own markdown
            # section (bugfix task 1.2); the note never preserves the other
            # two fields, so they stay empty rather than fabricated.
            structured = {
                "cause_hypothesis_note": _cause_hypothesis_from_note(note_text),
                "variable_groups_used": [],
                "variables_a_priorizar": [],
                "recommended_actions": [],
            }
        return {
            "circuito": circuito,
            "source": "vault_note",
            "content": note_text,
            "report_html": report_html,
            **structured,
        }

    if run_dir is None:
        return None
    data = load_validated_agent_output(run_dir, "expert-alignment")
    structured = _structured_fields(run_dir)

    return {
        "circuito": circuito,
        "source": "raw_json",
        "run_dir": str(run_dir),
        "content": data.get("sintesis_final", ""),
        "report_html": report_html,
        **structured,
    }


GRAPH_PATTERNS_SCHEMA_VERSION = "informe-gerencial-graph-patterns/v1"
GRAPH_PATTERNS_MIN_SUPPORT = 2


def load_graph_patterns(
    path: str | Path | None, sampled: Sequence[str]
) -> list[dict[str, Any]] | None:
    """Load + validate the cross-circuit graph-patterns JSON produced by the
    SKILL runbook's step 2.5 (`informe-gerencial-graph-patterns/v1`; design:
    "LLM step lives in the SKILL runbook, file handoff to Python").

    Pure I/O + validation, no LLM call, never raises (threat matrix: path
    injection via `--graph-patterns`):
    - `path is None` or the file does not exist -> `None` (distinguishes
      "step never ran" from "ran empty").
    - malformed/unreadable JSON -> `[]` (ran, but produced nothing usable).
    - each pattern's `circuitos` is intersected with `sampled` (a stale
      pattern may reference circuits outside the CURRENT sample), `soporte`
      is recomputed from that intersection, and the pattern is dropped if
      the recomputed `soporte < GRAPH_PATTERNS_MIN_SUPPORT`.
    """
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None

    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []

    if not isinstance(payload, dict):
        return []
    raw_patterns = payload.get("patterns")
    if not isinstance(raw_patterns, list):
        return []

    sampled_set = set(sampled)
    result: list[dict[str, Any]] = []
    for entry in raw_patterns:
        if not isinstance(entry, dict):
            continue
        tema = entry.get("tema")
        raw_circuitos = entry.get("circuitos")
        if not tema or not isinstance(raw_circuitos, list):
            continue
        circuitos = [c for c in raw_circuitos if c in sampled_set]
        soporte = len(circuitos)
        if soporte < GRAPH_PATTERNS_MIN_SUPPORT:
            continue
        result.append({"tema": tema, "circuitos": circuitos, "soporte": soporte})

    return result


def load_graph_view(path: str | Path | None) -> str | None:
    """Load the raw HTML text produced by `graph_view_builder build` (step
    2.5.6), if any -- pure I/O, no `graphify` import/call here (non-goal:
    this module stays graphify-free), never raises (threat matrix: path
    injection via `--graph-view`):
    - `path is None` or the file does not exist -> `None`.
    - unreadable (`OSError`/decode failure) -> `None`.
    - readable -> the raw HTML text, verbatim, for `_iframe_srcdoc` to embed.
    """
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    try:
        return candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


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
    mean+stdev: with <=12 samples a single extreme value drags mean/stdev
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


def _variable_priority_counter(loaded_content: Sequence[dict[str, Any] | None]) -> Counter:
    """Tally, once per circuit, which variables its own expert-alignment
    output prioritized (`variables_a_priorizar`) -- a real cross-circuit
    technical signal (which factors recur as prioritized across circuits),
    never an invented pattern.
    """
    counter: Counter = Counter()
    for content in loaded_content:
        if not content:
            continue
        seen: set[str] = set()
        for entry in content.get("variables_a_priorizar") or []:
            variable = entry.get("variable")
            if variable and variable not in seen:
                counter[variable] += 1
                seen.add(variable)
    return counter


def _variable_group_counter(loaded_content: Sequence[dict[str, Any] | None]) -> Counter:
    """Tally, once per circuit, which technical domain groups
    (`variable_groups_used`, e.g. Topologia/Entorno-Riesgo/Proteccion) its own
    historical key findings touched -- the historical agent's own domain
    classification, reused verbatim rather than re-derived here.
    """
    counter: Counter = Counter()
    for content in loaded_content:
        if not content:
            continue
        seen: set[str] = set()
        for group_name in content.get("variable_groups_used") or []:
            if group_name and group_name not in seen:
                counter[group_name] += 1
                seen.add(group_name)
    return counter


def _cause_theme_counter(loaded_content: Sequence[dict[str, Any] | None]) -> Counter:
    """Tally, once per circuit, which `_CAUSE_THEME_KEYWORDS` theme(s) appear
    in its own `cause_hypothesis_note` (historical agent output) -- pure
    deterministic substring matching against text the historical agent
    already wrote, never an LLM call or an invented cause.
    """
    counter: Counter = Counter()
    for content in loaded_content:
        if not content:
            continue
        note = (content.get("cause_hypothesis_note") or "").lower()
        if not note:
            continue
        for theme, keywords in _CAUSE_THEME_KEYWORDS.items():
            if any(keyword in note for keyword in keywords):
                counter[theme] += 1
    return counter


def _common_patterns(
    sampled_records: Sequence[dict[str, Any]], loaded_content: Sequence[dict[str, Any] | None]
) -> list[str]:
    """Cross-circuit TECHNICAL patterns -- criticality-tier mix, prioritized
    variables, technical domain groups, and recurring cause themes -- each
    derived from data already produced upstream by the per-circuit `/report`
    runs (expert-alignment/historical outputs), never merely descriptive
    counts of how the content itself was sourced.
    """
    patterns: list[str] = []
    n = len(sampled_records)

    tier_counts = Counter(record["criticidad"] for record in sampled_records if record.get("criticidad"))
    if tier_counts:
        tier_summary = ", ".join(f"{label} ({count})" for label, count in tier_counts.most_common())
        patterns.append(f"Distribución de criticidad en la muestra: {tier_summary}.")

    variable_counter = _variable_priority_counter(loaded_content)
    if variable_counter:
        var_summary = ", ".join(f"{var} ({count}/{n})" for var, count in variable_counter.most_common(5))
        patterns.append(
            f"Variables técnicas priorizadas de forma transversal en los circuitos analizados: {var_summary}."
        )

    group_counter = _variable_group_counter(loaded_content)
    if group_counter:
        group_summary = ", ".join(f"{grp} ({count}/{n})" for grp, count in group_counter.most_common())
        patterns.append(f"Dominios técnicos más frecuentes en los hallazgos individuales: {group_summary}.")

    theme_counter = _cause_theme_counter(loaded_content)
    if theme_counter:
        theme_summary = ", ".join(f"{theme} ({count}/{n})" for theme, count in theme_counter.most_common())
        patterns.append(f"Hipótesis de causa recurrentes entre los circuitos muestreados: {theme_summary}.")

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
    items = [
        f"UITI_VANO acumulado en la muestra del grupo '{label}': {total_uiti:,.2f} unidades, "
        f"con un promedio de {avg_uiti:,.2f} por circuito entre {n} circuitos representativos.",
        f"Frecuencia promedio de eventos por circuito en la ventana analizada: {avg_events:,.1f} eventos.",
    ]
    if missing_count:
        items.append(
            f"{missing_count} circuito(s) de la muestra sin contenido narrativo previo disponible."
        )
    return {
        "uiti_vano_total": total_uiti,
        "uiti_vano_promedio": avg_uiti,
        "eventos_promedio": avg_events,
        "circuitos_sin_contenido": missing_count,
        "items": items,
    }


def _recommended_actions(
    outliers: Sequence[dict[str, str]],
    missing_circuitos: Sequence[str],
    group: dict[str, Any],
    loaded_content: Sequence[dict[str, Any] | None],
) -> list[str]:
    label = group.get("label") or group.get("slug") or "grupo"
    actions = [f"Mantener monitoreo periódico del grupo '{label}' mediante /reporte-lote."]
    if outliers:
        names = ", ".join(item["circuito"] for item in outliers)
        actions.append(f"Priorizar inspección técnica en los circuitos atípicos: {names}.")
    if missing_circuitos:
        names = ", ".join(missing_circuitos)
        actions.append(f"Completar la generación de reportes individuales para: {names}.")

    # Technical, circuit-specific actions -- reused verbatim from each
    # circuit's own historical diagnosis (`recommended_actions`), never
    # invented here. Keeps this section from being purely generic/group-level.
    for content in loaded_content:
        if not content:
            continue
        circuito = content.get("circuito")
        top_action = next(iter(content.get("recommended_actions") or []), None)
        if circuito and top_action:
            actions.append(f"{circuito}: {top_action}")

    return actions


def _annex_per_circuit(
    sampled_records: Sequence[dict[str, Any]], loaded_content: Sequence[dict[str, Any] | None]
) -> list[dict[str, Any]]:
    """Build the per-circuit annex row: `extracto` is the FULL narrative
    summary (never truncated -- a cut-off paragraph is worse than a long
    one), and `report_html` is the ONLY file this module cites to the user
    (the circuit's own rendered `/report`, never the internal JSON/markdown
    run artifacts `fuente` merely categorizes internally).
    """
    annex: list[dict[str, Any]] = []
    for record, content in zip(sampled_records, loaded_content):
        if content is None:
            fuente, extracto, report_html = "sin_contenido", "Sin contenido disponible.", None
        else:
            fuente = content.get("source", "desconocido")
            extracto = str(content.get("content", "")).strip()
            report_html = content.get("report_html")
        annex.append(
            {
                "circuito": record["circuito"],
                "criticidad": record.get("criticidad"),
                "fuente": fuente,
                "extracto": extracto,
                "report_html": report_html,
            }
        )
    return annex


def _executive_summary(
    sampled_records: Sequence[dict[str, Any]],
    group: dict[str, Any],
    outliers: Sequence[dict[str, str]],
    loaded_content: Sequence[dict[str, Any] | None],
) -> list[str]:
    """Build 5-7 short (~3-line) executive-summary items covering common
    technical patterns, possible/common identified causes, and relevant
    failure-driving factors -- never a single descriptive paragraph.

    Five baseline items are always derivable from `sampled_records` alone
    (framing, sampling method, aggregate risk, tier mix/top-variable
    fallback, top single circuit); up to two more are appended, in priority
    order, only when the sampled circuits' own loaded content actually
    supports them (outliers, then prioritized-variable/cause-theme/technical
    -domain/missing-content signal) -- capped at 7 total either way.
    """
    label = group.get("label") or group.get("slug") or "grupo"
    n = len(sampled_records)
    universe = group.get("circuit_count", n)

    items: list[str] = [
        f"Informe gerencial del grupo '{label}': se analizaron {n} circuitos representativos "
        f"de un universo de {universe} en la ventana evaluada.",
        f"Los {n} circuitos se seleccionaron por menor distancia a su centroide de criticidad, "
        "maximizando su representatividad estadística del grupo muestreado.",
    ]

    total_uiti = sum(record["uiti_vano_sum"] for record in sampled_records)
    avg_events = sum(record["event_count"] for record in sampled_records) / n if n else 0.0
    items.append(
        f"El grupo acumula {total_uiti:,.2f} unidades de UITI_VANO con un promedio de "
        f"{avg_events:,.1f} eventos por circuito en la ventana analizada."
    )

    variable_counter = _variable_priority_counter(loaded_content)
    if variable_counter:
        top_vars = ", ".join(f"{var} ({count}/{n})" for var, count in variable_counter.most_common(3))
        items.append(
            f"Variables técnicas priorizadas de forma transversal en la muestra: {top_vars}, "
            "señalando factores recurrentes asociados a las fallas."
        )
    else:
        tier_counts = Counter(record["criticidad"] for record in sampled_records if record.get("criticidad"))
        tier_summary = ", ".join(f"{tier_label} ({count})" for tier_label, count in tier_counts.most_common())
        items.append(f"Distribución de criticidad en la muestra: {tier_summary}." if tier_summary else "Sin distribución de criticidad disponible en la muestra.")

    if sampled_records:
        top_record = max(sampled_records, key=lambda record: record["uiti_vano_sum"])
        items.append(
            f"El circuito con mayor UITI_VANO acumulado en la muestra es {top_record['circuito']} "
            f"({top_record['uiti_vano_sum']:,.2f}), de mayor peso relativo en el riesgo del grupo."
        )

    conditional: list[str] = []
    if outliers:
        names = ", ".join(item["circuito"] for item in outliers)
        conditional.append(
            f"Se identificaron {len(outliers)} circuito(s) atípico(s) ({names}) con desviación "
            "marcada en UITI_VANO o frecuencia de eventos respecto a la mediana muestral."
        )

    theme_counter = _cause_theme_counter(loaded_content)
    if theme_counter:
        top_themes = ", ".join(f"{theme} ({count}/{n})" for theme, count in theme_counter.most_common(2))
        conditional.append(
            f"Las hipótesis de causa más recurrentes entre los circuitos apuntan a: {top_themes}, "
            "coherentes con los hallazgos técnicos individuales."
        )

    group_counter = _variable_group_counter(loaded_content)
    if group_counter:
        top_group, top_group_count = group_counter.most_common(1)[0]
        conditional.append(
            f"El dominio técnico más frecuente en los hallazgos individuales es '{top_group}', "
            f"presente en {top_group_count} de {n} circuitos analizados."
        )

    missing_count = sum(1 for content in loaded_content if content is None)
    if missing_count:
        conditional.append(
            f"{missing_count} circuito(s) de la muestra no cuentan con contenido narrativo previo "
            "disponible para este informe."
        )

    items.extend(conditional[: max(0, 7 - len(items))])
    return items[:7]


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
        "resumen_ejecutivo": _executive_summary(sampled_records, group, outliers, loaded_content),
        "patrones_comunes": _common_patterns(sampled_records, loaded_content),
        "circuitos_atipicos": outliers,
        "riesgo_agregado": _aggregate_risk(sampled_records, loaded_content, group),
        "acciones_recomendadas": _recommended_actions(outliers, missing_circuitos, group, loaded_content),
        "anexo_por_circuito": _annex_per_circuit(sampled_records, loaded_content),
    }


def _escape(value: Any) -> str:
    return html_lib.escape("" if value is None else str(value))


def _iframe_srcdoc(html: str, *, height: int = 620) -> str:
    """Wrap `html` in a self-contained `<iframe srcdoc="...">` embed -- a
    small, deliberate 4-line duplicate of `plotting.py`'s own nested
    `_iframe_srcdoc` closure (design D3), reusing THIS module's own
    `_escape` rather than importing from `plotting.py` (that closure is not
    importable without a `plotting.py` refactor, explicitly out of scope).
    """
    if not html:
        return ""
    return (
        f"<iframe class='embedded-map-frame' srcdoc=\"{_escape(html)}\" "
        f"loading='lazy' style='width:100%;height:{height}px;border:0;background:#ffffff;'></iframe>"
    )


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


def _report_reference_html(report_html: str | None) -> str:
    """Render the ONLY file this module ever cites to the user: the
    circuit's own rendered `/report` HTML (never the internal JSON/markdown
    run artifacts `load_circuit_content` reads from).
    """
    if not report_html:
        return "<span class='muted'>Informe no disponible</span>"
    return _escape(Path(report_html).name)


def _graph_patterns_html(
    graph_patterns: list[dict[str, Any]] | None,
    graph_view_html: str | None,
    *,
    n_sampled: int,
) -> str:
    """Render the "Patrones cross-circuito (grafo)" subsection per the render
    states (design: "Section always assembled in Python" / D5 "3-way graph-
    embed state"): omitted entirely when `n_sampled < 2` (empty string,
    caller skips the whole `<section>`); muted "not available this run" when
    the patterns step never produced a file (`graph_patterns is None`);
    muted "no recurring pattern" when it ran but produced nothing meeting
    min-support (`graph_patterns == []`); otherwise the populated itemized
    pattern list, always carrying the visible LLM-assisted provenance badge
    (spec: "Provenance labeling of the graph subsection") -- PLUS, only when
    the itemized list itself is populated, the embedded `graph_view_html`
    figure (`_iframe_srcdoc`) when available, or a muted "figure not
    available this run" indicator when it is not (independent degradation
    from the patterns list, design D5/spec "Graceful degradation").
    """
    if n_sampled < 2:
        return ""

    badge = '<p class="badge-llm">Interpretación asistida por LLM (grafo)</p>'
    if graph_patterns is None:
        body = "<p class='muted'>análisis de grafo no disponible en esta corrida.</p>"
    elif not graph_patterns:
        body = "<p class='muted'>sin patrones recurrentes con soporte &gt;= 2.</p>"
    else:
        rows = "".join(
            "<li>"
            f"{_escape(pattern['tema'])} &mdash; circuitos "
            f"[{_escape(', '.join(pattern['circuitos']))}] (soporte {_escape(pattern['soporte'])})"
            "</li>"
            for pattern in graph_patterns
        )
        body = f"<ul>{rows}</ul>"
        if graph_view_html:
            body += _iframe_srcdoc(graph_view_html)
        else:
            body += "<p class='muted'>figura de grafo no disponible en esta corrida.</p>"

    return f"""
<section class="report-section">
<h2>Patrones cross-circuito (grafo)</h2>
{badge}
{body}
</section>
"""


def _annex_html(annex: Sequence[dict[str, Any]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_escape(entry['circuito'])}</td>"
        f"<td>{_escape(entry.get('criticidad'))}</td>"
        f"<td>{_report_reference_html(entry.get('report_html'))}</td>"
        f"<td>{_escape(entry['extracto'])}</td>"
        "</tr>"
        for entry in annex
    )
    return (
        "<table class='annex-table'><thead><tr>"
        "<th>Circuito</th><th>Criticidad</th><th>Informe del circuito</th><th>Resumen completo</th>"
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
.badge-llm { display: inline-block; background: #ede9fe; color: #5b21b6; border-radius: 999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; margin: 0 0 8px; }
.badge-deterministic { display: inline-block; background: #dcfce7; color: #166534; border-radius: 999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; margin: 0 0 8px; }
"""


def render_managerial_report(
    raw_df: pd.DataFrame,
    *,
    synthesis: dict[str, Any],
    group: dict[str, Any],
    resolved_window: dict[str, Any],
    sampled: Sequence[str],
    graph_patterns: list[dict[str, Any]] | None = None,
    graph_view_html: str | None = None,
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
    graph_section_html = _graph_patterns_html(graph_patterns, graph_view_html, n_sampled=len(sampled))

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
{_list_html(synthesis['resumen_ejecutivo'])}
</section>

<section class="report-section">
<h2>Patrones comunes</h2>
<p class="badge-deterministic">Cálculo determinista</p>
{_list_html(synthesis['patrones_comunes'])}
</section>
{graph_section_html}
<section class="report-section">
<h2>Circuitos atípicos (outliers)</h2>
{_outliers_html(synthesis['circuitos_atipicos'])}
</section>

<section class="report-section">
<h2>Riesgo agregado</h2>
{_list_html(synthesis['riesgo_agregado']['items'])}
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
    graph_patterns_path: str | Path | None = None,
    graph_view_path: str | Path | None = None,
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
    graph_patterns = load_graph_patterns(graph_patterns_path, sampled)
    graph_view_html = load_graph_view(graph_view_path)

    synthesis = synthesize(sampled_records, loaded_content, group)
    html = render_managerial_report(
        frame,
        synthesis=synthesis,
        group=group,
        resolved_window=resolved_window,
        sampled=sampled,
        graph_patterns=graph_patterns,
        graph_view_html=graph_view_html,
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
    render_command.add_argument("--graph-patterns")
    render_command.add_argument("--graph-view")

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
            graph_patterns_path=args.graph_patterns,
            graph_view_path=args.graph_view,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status == "success" else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
