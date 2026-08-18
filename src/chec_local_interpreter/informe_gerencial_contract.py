"""Shared runtime contract for `/informe-gerencial` -- cross-circuit managerial
report synthesized across a criticality group's most representative circuits.

Sibling of `circuit_clustering_contract.py`/`batch_report_contract.py`: this
module resolves a criticality-group slug (or `todos`) to its full circuit
universe via `compute_circuit_criticality_groups` (reusing
`batch_report_contract`'s `normalize_request`/`GROUP_SLUGS`/
`_dataset_date_range` for argument and date-window resolution ONLY --
`batch_report_contract.preflight_batch`'s own `todos` bypass is NEVER called
or modified here; this module always computes bands via `ranking_circuitos`
for every group including `todos`), then
samples the top-12 WORST circuits of the band (largest `vanos_criticos`,
i.e. the head of the ranking's own `posicion`), detects any of them missing a
prior `/report` run, and loads their narrative content.

Content sourcing (Phase 3): vault-note-preferred, with the raw
`expert-alignment.out.json` under
`reports/reportescircuitos/runs/{canonical_circuit}/` as the fallback -- both
paths live in `load_circuit_content`.

`find_latest_run` here deliberately does NOT delegate to the same-named
`vault_note_contract.find_latest_run`, even though that module now exists.
The two answer different questions: that one returns the newest run directory
outright, this one returns the newest run whose OWN
`expert-alignment.out.json` validates -- i.e. a run that actually finished.
`detect_missing_runs` depends on that stricter reading, so a half-written run
is reported as missing instead of silently passing as complete.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

import pandas as pd

from chec_local_interpreter.agent_output import ReportPipelineError, load_validated_agent_output
from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text
from chec_local_interpreter.batch_report_contract import (
    ALL_GROUPS_SLUG,
    GROUP_SLUGS as RANKING_GROUP_SLUGS,
    GROUP_SLUG_TO_LABEL as RANKING_SLUG_TO_LABEL,
    VALID_GROUP_SLUGS,
)
from chec_local_interpreter.batch_report_contract import normalize_request as _batch_normalize_request
from chec_local_interpreter.circuit_clustering_contract import RuntimeMetadata, _dataset_date_range
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.informe_estilo import (
    CSS_IDENTIDAD,
    escudo_chec_html,
    pie_agentes_html,
)
from chec_local_interpreter.config import DEFAULT_DATA_PATH, PROJECT_ROOT
from chec_local_interpreter.data_loader import filter_events, load_dataset
from chec_local_interpreter.plotting import plot_ranking_circuitos
from chec_local_interpreter.ranking_circuitos import ranking_circuitos

SCHEMA_VERSION = "informe-gerencial-contract/v1"

TOP_N_REPRESENTATIVE = 12

# El vocabulario de grupos sale del RANKING del cuaderno 02 -- las cuatro bandas que
# pinta el tablero de agrupamiento y que /report ya cita --, no del K-Means de circuitos
# sobre eventos x UITI. Los dos coexistian con la MISMA palabra queriendo decir cosas
# distintas: medido sobre los 208 circuitos, "Riesgo Alto" eran 16 circuitos por K-Means
# y 7 por el ranking, y solo 3 estaban en los dos. El informe agrupaba por un criterio
# que su propia figura no mostraba.
#
# El allowlist se sigue COMPARTIENDO con `batch_report_contract` -- se reexporta con los
# nombres de aqui -- porque los dos comandos migraron juntos y una sola definicion es lo
# que impide que se vuelvan a separar. Si algun dia uno cambia de agrupacion, lo que hay
# que partir es el allowlist, no copiarlo.

DEFAULT_RUNS_ROOT = PROJECT_ROOT / "reports" / "reportescircuitos" / "runs"
DEFAULT_VAULT_ROOT = PROJECT_ROOT / "reports" / "vault"
DEFAULT_REPORT_OUTPUT_ROOT = PROJECT_ROOT / "reports" / "informesgerenciales"
# Mirrors `plotting.render_llm_analysis`'s own default `output_dir` -- the root
# where every per-circuit `/report` HTML lands. This is the ONLY "file" this
# module is allowed to cite to the user (never the internal JSON/markdown run
# artifacts); see `_circuit_report_html_path`.
DEFAULT_CIRCUIT_HTML_ROOT = PROJECT_ROOT / "reports" / "reportescircuitos" / "html"

# Deterministic, non-LLM keyword buckets used to mine shared causal themes
# from each circuit's own `cause_hypothesis_note` (historical agent output).
# Substring matches only -- no inference, no invented causes -- just
# cross-circuit tallying of themes the historical agent already wrote.
#
# Keywords are written WITHOUT accents on purpose: `cause_themes` strips
# accents from the note before matching, because the historical agent writes
# some notes accented ("condiciones atmosféricas") and others not
# ("condiciones atmosfericas") for the same circuit corpus. Measured over the
# 30 notes on disk: every one of them lands in at least one bucket.
CAUSE_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fauna": ("fauna", "animal"),
    "conductor/vegetación": ("conductor", "vegetaci", "arbol", "rama"),
    "clima/atmosférico": ("atmosf", "clima", "viento", "lluvia", "precipita", "rafaga"),
    "línea MT / falla física": ("media tension", "linea mt", " rota", " roto"),
    "protección/maniobra": ("protecci", "maniobra", "transformador", "seccionador"),
    "topológico/recurrencia de vanos": ("topologic", "recurrent", "vano", "cluster"),
}

def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def cause_themes(text: str | None) -> list[str]:
    """Bucket a free-text cause hypothesis into the shared `CAUSE_THEME_KEYWORDS`
    themes, accent-insensitively.

    Single-sourced on purpose: both this module's "Hipótesis de causa
    recurrentes" prose and `intervention_graph`'s radial figure call it, so the
    report's text and its figure can never name different causes for the same
    note. Deterministic (declaration order), never raises.
    """
    if not text:
        return []
    normalized = _strip_accents(text)
    return [
        theme
        for theme, keywords in CAUSE_THEME_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    ]

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
    """Los `limit` circuitos PEORES de la banda: mayor conteo de vanos en Medio-Alto +
    Alto, que es el puesto que el ranking ya calcula y que /report cita en prosa.

    El criterio anterior era la menor `centroid_distance` al centroide de su clase de
    K-Means -- el circuito mas TIPICO de su grupo --. El ranking no tiene centroides de
    circuito, asi que ese numero no existe aqui; y dentro de una banda de percentil el
    circuito tipico no es el que hay que atender. Se elige por criticidad.

    Sesgo que esto introduce, y que conviene tener presente al leer el informe: los doce
    quedan pegados al borde SUPERIOR de la banda. El informe describe la cola peor del
    grupo, no el grupo entero. Cuando la banda trae `limit` circuitos o menos entran
    todos, que es el caso de "Riesgo Alto" -- son el 3% superior de la flota.

    Desempate por nombre ascendente (`sort_index()` antes de `nlargest`, que con
    `keep="first"` conserva el orden de llegada) para que dos corridas sobre los mismos
    datos elijan exactamente los mismos doce.
    """
    if len(df_coords) <= limit:
        return df_coords
    return df_coords.sort_index().nlargest(limit, "vanos_criticos")


def resolve_group_dataframe(
    filtered_df: pd.DataFrame, grupo: str, criticidad: str | None
) -> pd.DataFrame:
    """Resuelve un slug de banda (o `todos`) a su universo de circuitos, con el RANKING
    del cuaderno 02: el conteo de vanos en Medio-Alto + Alto por circuito, cortado en
    P50/P75/P97.

    Es exactamente el mismo calculo que dibuja la barra del tablero de agrupamiento y el
    que `context_builder` ya cita en el informe por circuito. Antes salia de
    `compute_circuit_criticality_groups` -- K-Means sobre eventos x UITI del circuito --,
    que es otro metodo Y otro vocabulario: cinco bandas con "Riesgo Muy Alto" y "Riesgo
    Medio-Bajo", que la barra no tiene. El gerencial era el ultimo consumidor que
    agrupaba por un criterio que su propia figura no mostraba.

    `batch_report_contract.preflight_batch` sigue sin llamarse ni modificarse.

    Devuelve el marco indexado por circuito, con las columnas del ranking
    (`vanos_criticos`, `vanos_medio_alto`, `vanos_alto`, `vanos_con_eventos`,
    `uiti_total`, `eventos_total`, `posicion`) mas `criticidad`, que lleva la banda.
    """
    tabla = ranking_circuitos(filtered_df).tabla
    if tabla.empty:
        return tabla
    marco = (tabla.rename(columns={"rango": "criticidad"})
             .set_index("circuito")
             .drop(columns=["color"], errors="ignore"))
    marco.index.name = "CIRCUITO"
    if grupo == ALL_GROUPS_SLUG:
        return marco
    return marco[marco["criticidad"] == criticidad]


# ---------------------------------------------------------------------------
# Phase 3: missing-run detection + content loading
# ---------------------------------------------------------------------------


def find_latest_run(circuito: str, *, runs_root: str | Path | None = None) -> Path | None:
    """Find the newest run directory for `circuito` that has a validated own
    `expert-alignment.out.json` (a fully completed prior `/report` run).

    Not a delegate of `vault_note_contract.find_latest_run` despite the shared
    name -- see the module docstring: that one takes the newest run dir as-is,
    this one requires the run to have actually finished.

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
    `cause_hypothesis_note`/`variable_groups_used`/`recommended_actions`/
    `headline`/`key_finding_titles` (historical) from `run_dir`'s own JSON
    artifacts -- the authoritative source already on disk, shared by BOTH the
    vault-note and raw-JSON branches of `load_circuit_content` (bugfix: the
    vault branch previously hardcoded these to `None`/`[]` instead of reusing
    this same extraction). `headline`/`key_finding_titles` feed the annex's
    short human-readable summary (see `_annex_summary_lines`) so the
    managerial report never has to dump a circuit's full raw narrative text.
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
    headline: str | None = None
    key_finding_titles: list[str] = []
    try:
        historical_data = load_validated_agent_output(run_dir, "historical")
    except (ReportPipelineError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        historical_data = None
    if historical_data:
        cause_hypothesis_note = historical_data.get("cause_hypothesis_note")
        recommended_actions = list(historical_data.get("recommended_actions") or [])
        headline = historical_data.get("headline")
        for finding in historical_data.get("key_findings") or []:
            variable_groups_used.extend(finding.get("variable_groups_used") or [])
            title = finding.get("title")
            if title:
                key_finding_titles.append(title)

    return {
        "cause_hypothesis_note": cause_hypothesis_note,
        "variable_groups_used": variable_groups_used,
        "variables_a_priorizar": variables_a_priorizar,
        "recommended_actions": recommended_actions,
        "headline": headline,
        "key_finding_titles": key_finding_titles,
    }


def _orden_ventana(etiqueta: str) -> tuple[int, str]:
    """`V10` va DESPUES de `V9`, no entre `V1` y `V2`.

    El mismo criterio que `mil_inferencia._orden_ventana`, repetido aqui y no importado
    a proposito: este modulo no depende del artefacto MIL ni de torch, y traerse ese
    import por una funcion de cuatro lineas le costaria el arranque entero.
    """
    resto = str(etiqueta).lstrip("Vv")
    return (int(resto), "") if resto.isdigit() else (10**9, str(etiqueta))


def ventanas_del_grupo(
    sampled: Sequence[str],
    *,
    runs_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """En que VENTANAS se concentra la criticidad del grupo.

    El informe agregaba por circuito y perdia la dimension en la que el modelo trabaja:
    la unidad del MIL es la bolsa `(vano, ventana)`, y cada `/report` estudia TRES
    ventanas de su circuito. Sumando los circuitos sin mirar la ventana, dos hallazgos
    de meses distintos se leen como el mismo problema.

    La fuente es el SOBRE de inferencia (`inference.bc.json`) y no la salida del agente.
    Medido sobre las corridas en disco, los escenarios que el agente devuelve traen
    `nombre`, `interpretacion` y `provenance` -- sin `ventana` ni `vanos_criticos`. Lo
    que `prepare` dejo en el sobre si trae la ventana, cuantos vanos tiene, cuales son
    criticos y cuales alcanzan el grupo Bajo.

    Nunca lanza: un circuito sin corrida, o con un sobre ilegible, simplemente no aporta
    ventanas. El informe ya declara en otra parte cuales quedaron sin correr.
    """
    acumulado: dict[str, dict[str, Any]] = {}
    for circuito in sampled or ():
        run_dir = find_latest_run(str(circuito), runs_root=runs_root)
        if run_dir is None:
            continue
        try:
            sobre = json.loads((run_dir / "inference.bc.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        periodos = sobre.get("periodos_ventana") or {}
        for escenario in sobre.get("escenarios") or []:
            ventana = str(escenario.get("ventana") or "").strip()
            if not ventana:
                continue
            criticos = list(escenario.get("vanos_criticos") or [])
            fila = acumulado.setdefault(ventana, {
                "ventana": ventana, "periodo": "", "circuitos": 0,
                "vanos_criticos": 0, "bajan_de_grupo": 0, "alcanzan_bajo": 0,
            })
            fila["circuitos"] += 1
            fila["vanos_criticos"] += len(criticos)
            fila["alcanzan_bajo"] += sum(1 for c in criticos if c.get("alcanza"))
            # Bajar un escalon sin llegar a Bajo tambien es efecto de la obra. Medido
            # sobre DON23L14 V11: de los 16 vanos que el plan mueve, 8 llegan a Bajo y
            # 8 bajan un grupo sin llegar. Contando solo los primeros, la mitad del
            # efecto desaparece, y una ventana donde nada llega a Bajo pero todo baja un
            # escalon se lee como una ventana sin nada que hacer.
            #
            # `alcanza or baja_de_grupo` y no solo el campo nuevo: las corridas
            # anteriores al cambio no lo traen, y llegar a Bajo ES bajar de grupo. Se
            # cae a lo que si se puede afirmar, sin inventar bajadas.
            fila["bajan_de_grupo"] += sum(
                1 for c in criticos if c.get("baja_de_grupo") or c.get("alcanza"))
            # El periodo lo escribe el primero que lo traiga: es el mismo calendario
            # para todos los circuitos, porque la rejilla de ventanas es del dataset.
            if not fila["periodo"] and periodos.get(ventana):
                fila["periodo"] = str(periodos[ventana])
    return [acumulado[v] for v in sorted(acumulado, key=_orden_ventana)]


def figura_por_ventana(filas: Sequence[Mapping[str, Any]]):
    """Vanos criticos contra los que la intervencion alcanza a sacar del grupo critico.

    Las dos cifras juntas SON la lectura: cuantos vanos hay que atender en esa ventana,
    y en cuantos la obra basta. Una sola de las dos deja media decision.
    """
    filas = list(filas or ())
    if not filas:
        return None

    import plotly.graph_objects as go

    etiquetas = [str(f["ventana"]) for f in filas]
    hover = [
        f"<b>Ventana {f['ventana']}</b>"
        + (f"<br>{f['periodo']}" if f.get("periodo") else "")
        + f"<br>{f.get('circuitos', 0)} circuitos del grupo la estudiaron"
        f"<br>{f.get('vanos_criticos', 0)} vanos críticos"
        f"<br>{f.get('bajan_de_grupo', 0)} bajan de grupo"
        f"<br>{f.get('alcanzan_bajo', 0)} alcanzan el grupo Bajo"
        for f in filas
    ]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=etiquetas, y=[int(f.get("vanos_criticos", 0)) for f in filas],
        name="Vanos críticos",
        marker=dict(color="#c62828", line=dict(width=0.4, color="#5b4a48")),
        hovertext=hover, hoverinfo="text",
    ))
    # Tres cifras y no dos: cuantos hay que atender, en cuantos la obra los baja un
    # escalon, y en cuantos los saca del todo. La del medio era la que faltaba.
    fig.add_trace(go.Bar(
        x=etiquetas, y=[int(f.get("bajan_de_grupo", 0)) for f in filas],
        name="Bajan de grupo",
        marker=dict(color="#ef6c00", line=dict(width=0.4, color="#5b4a48")),
        hovertext=hover, hoverinfo="text",
    ))
    fig.add_trace(go.Bar(
        x=etiquetas, y=[int(f.get("alcanzan_bajo", 0)) for f in filas],
        name="Alcanzan el grupo Bajo",
        marker=dict(color="#1a9641", line=dict(width=0.4, color="#5b4a48"),
                    pattern=dict(shape="/", solidity=0.35, fgcolor="#5b4a48")),
        hovertext=hover, hoverinfo="text",
    ))
    fig.update_layout(
        height=320, barmode="group", bargap=0.28,
        margin=dict(l=10, r=10, t=26, b=10),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        font=dict(size=11, color="#2b2b2b"),
    )
    fig.update_xaxes(title_text="Ventana", type="category")
    fig.update_yaxes(title_text="Vanos", rangemode="tozero", gridcolor="#e2e8f0")
    return fig


def _ventanas_html(filas: Sequence[Mapping[str, Any]]) -> str:
    """La seccion "Concentracion por ventana", o nada si no hay ventanas.

    Determinista: sale de los sobres que `prepare` dejo en disco, sin pasar por ningun
    agente, y por eso lleva el mismo distintivo que las demas secciones calculadas.
    """
    filas = list(filas or ())
    if not filas:
        return ""

    figura = figura_por_ventana(filas)
    grafica = ("" if figura is None else
               figura.to_html(full_html=False, include_plotlyjs=False,
                              div_id="grafica-ventanas"))
    renglones = "".join(
        f"<tr><td><strong>{_escape(f['ventana'])}</strong></td>"
        f"<td>{_escape(f.get('periodo') or '&mdash;')}</td>"
        f"<td>{_escape(f.get('circuitos', 0))}</td>"
        f"<td>{_escape(f.get('vanos_criticos', 0))}</td>"
        f"<td>{_escape(f.get('bajan_de_grupo', 0))}</td>"
        f"<td>{_escape(f.get('alcanzan_bajo', 0))}</td></tr>"
        for f in filas
    )
    return f"""
<section class="report-section">
<h2>Concentración por ventana</h2>
<p class="badge-deterministic">Cálculo determinista</p>
<p>La unidad del modelo es la celda <em>vano &times; ventana</em>, y cada informe de
circuito estudia tres ventanas. Aquí se suman las de todos los circuitos muestreados:
dónde se concentra el problema del grupo en el tiempo, y en cuántos de esos vanos la
intervención alcanza a sacarlos del grupo crítico.</p>
{grafica}
<table class="tabla-ventanas">
<thead><tr><th>Ventana</th><th>Período</th><th>Circuitos</th>
<th>Vanos críticos</th><th>Bajan de grupo</th><th>Alcanzan Bajo</th></tr></thead>
<tbody>{renglones}</tbody>
</table>
</section>
"""


def load_circuit_content(
    circuito: str,
    *,
    runs_root: str | Path | None = None,
    vault_root: str | Path | None = None,
    html_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load narrative content for `circuito`: vault note preferred, raw JSON
    run artifact as fallback (spec: "Content sourcing").

    `reports/vault/{canonical}.md` is checked first; the raw run artifact is
    the fallback. Returns `None` when neither a vault note nor a completed
    prior run exists.

    Beyond the base `circuito`/`source`/`content` shape, the raw-JSON path
    also surfaces the richer technical signal already produced upstream by
    the per-circuit `/report` run -- `report_html` (the ONLY file citable to
    the user), `variables_a_priorizar` (expert-alignment), and
    `cause_hypothesis_note`/`variable_groups_used`/`recommended_actions`
    (historical) -- so `synthesize()` can build technical, non-descriptive
    cross-circuit sections instead of re-deriving this from scratch. The
    vault-note branch populates the SAME fields from the same run artifacts
    via `_structured_fields` whenever a run dir is still resolvable; when it
    is not, only `cause_hypothesis_note` is recovered (parsed from the note's
    own markdown section) and the rest stay empty rather than fabricated.
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
                "headline": None,
                "key_finding_titles": [],
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
    """Valida y normaliza los argumentos de linea de comandos a un
    `InformeGerencialRequest`.

    Reusa `batch_report_contract.normalize_request` para la MISMA validacion de
    `grupo`/`fecha_inicio`/`fecha_fin` (allowlist de `VALID_GROUP_SLUGS`, regla de fechas
    en pareja), asi los dos contratos no se pueden separar en que es un `grupo` valido, y
    reempaqueta el resultado en el tipo de peticion de este modulo.
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

    uiti_median = statistics.median(r["uiti_total"] for r in sampled_records)
    event_median = statistics.median(r["eventos_total"] for r in sampled_records)

    outliers: list[dict[str, str]] = []
    for record in sampled_records:
        reasons: list[str] = []
        if uiti_median > 0 and record["uiti_total"] > 2 * uiti_median:
            reasons.append(
                f"UITI_VANO acumulado ({record['uiti_total']:,.2f}) más del doble de la "
                f"mediana del grupo muestreado ({uiti_median:,.2f})"
            )
        if event_median > 0 and record["eventos_total"] < 0.5 * event_median:
            reasons.append(
                f"eventos por vano ({record['eventos_total']:,.0f}) muy por debajo de la "
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
    """Tally, once per circuit, which `CAUSE_THEME_KEYWORDS` theme(s) appear
    in its own `cause_hypothesis_note` (historical agent output) -- pure
    deterministic substring matching against text the historical agent
    already wrote, never an LLM call or an invented cause.

    Delegates the bucketing to the shared `cause_themes` helper so this prose
    and `intervention_graph`'s radial figure can never disagree.
    """
    counter: Counter = Counter()
    for content in loaded_content:
        if not content:
            continue
        for theme in cause_themes(content.get("cause_hypothesis_note")):
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
    uiti_values = [record["uiti_total"] for record in sampled_records]
    total_uiti = sum(uiti_values)
    n = len(sampled_records)
    avg_uiti = total_uiti / n if n else 0.0
    total_criticos = sum(record["vanos_criticos"] for record in sampled_records)
    missing_count = sum(1 for content in loaded_content if content is None)

    label = group.get("label") or group.get("slug") or "grupo"
    items = [
        # El conteo de vanos criticos primero: es la magnitud que DEFINE la banda, y por
        # tanto la unica que explica por que estos circuitos estan en este informe.
        f"Los {n} circuitos de la muestra suman {total_criticos:,} vanos en Medio-Alto + "
        f"Alto, que es la magnitud con la que se define la banda '{label}'.",
        f"UITI_VANO acumulado en la muestra del grupo '{label}': {total_uiti:,.2f} unidades, "
        f"con un promedio de {avg_uiti:,.2f} por circuito entre {n} circuitos.",
    ]
    if missing_count:
        items.append(
            f"{missing_count} circuito(s) de la muestra sin contenido narrativo previo disponible."
        )
    return {
        "vanos_criticos_total": total_criticos,
        "uiti_vano_total": total_uiti,
        "uiti_vano_promedio": avg_uiti,
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


def _shorten(text: str, *, limit: int = 220) -> str:
    """Collapse whitespace/newlines and truncate at a word boundary with an
    ellipsis -- used only as a last-resort fallback when no structured
    finding fields are available (see `_annex_summary_lines`), never for the
    normal case where `headline`/`key_finding_titles` already are short.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.;])\s+")


def _hypothesis_clauses(text: str) -> list[str]:
    """Split a `cause_hypothesis_note` into its component clauses (sentence/
    semicolon boundaries) so the annex can render it as SUB-ITEMS under
    "Hipótesis de causa" instead of one dense paragraph -- this module's
    agent-authored hypotheses are routinely one long enumerated sentence
    using ';'/numbered markers between points, not separate '.'-delimited
    sentences (see `_annex_summary_lines`/`_annex_html`). Never truncates or
    drops any text -- every clause survives, whitespace-collapsed only.

    Always returns at least one clause (the whole collapsed text, when there
    is nothing to split on) so the annex's sub-item structure is the SAME
    shape on every run regardless of how a given hypothesis happens to be
    punctuated (design: "consistent flow across runs").
    """
    collapsed = " ".join(text.split())
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(collapsed) if c.strip()]
    return clauses or [collapsed]


def _annex_summary_lines(content: dict[str, Any] | None) -> list[str | dict[str, Any]]:
    """Build a short, human-readable 3-4 item summary of a circuit's main
    findings for the managerial annex, from already-extracted structured
    fields (`headline`, `key_finding_titles`, `cause_hypothesis_note`,
    `variables_a_priorizar`) -- NEVER the full raw vault-note/report
    narrative text, which can run to many paragraphs and is unreadable
    inside a table cell (this replaces the previous `extracto` field, which
    dumped that full text verbatim).

    Every item is a plain string EXCEPT the cause hypothesis, which is a
    `{"label": "Hipótesis de causa", "items": [...]}` dict -- rendered by
    `_annex_html` as a labeled sub-list, one `<li>` per clause from
    `_hypothesis_clauses`, so a long hypothesis (always shown COMPLETE, never
    truncated) reads as scannable sub-points instead of one wall of text.
    """
    if content is None:
        return ["Sin contenido disponible."]

    lines: list[str | dict[str, Any]] = []

    headline = content.get("headline")
    if headline:
        lines.append(str(headline))

    for title in (content.get("key_finding_titles") or [])[:2]:
        lines.append(f"Hallazgo: {title}")

    cause = content.get("cause_hypothesis_note")
    if cause and len(lines) < 4:
        lines.append({"label": "Hipótesis de causa", "items": _hypothesis_clauses(cause)})

    if len(lines) < 4:
        variables = [
            item.get("variable")
            for item in (content.get("variables_a_priorizar") or [])
            if item.get("variable")
        ][:3]
        if variables:
            lines.append(f"Variables priorizadas: {', '.join(variables)}")

    if not lines:
        # No structured fields recovered at all (e.g. a vault note whose
        # run_dir is no longer resolvable) -- fall back to a SHORTENED
        # excerpt of the raw content rather than showing nothing, but never
        # the full unreadable dump.
        raw = str(content.get("content", "")).strip()
        lines.append(_shorten(raw) if raw else "Sin hallazgos estructurados disponibles.")

    return lines[:4]


def _annex_per_circuit(
    sampled_records: Sequence[dict[str, Any]], loaded_content: Sequence[dict[str, Any] | None]
) -> list[dict[str, Any]]:
    """Build the per-circuit annex row: `resumen` is a short (3-4 item),
    human-readable summary of the circuit's main findings (see
    `_annex_summary_lines`), and `report_html` is the ONLY file this module
    cites to the user for the complete report (the circuit's own rendered
    `/report`, never the internal JSON/markdown run artifacts `fuente`
    merely categorizes internally).
    """
    annex: list[dict[str, Any]] = []
    for record, content in zip(sampled_records, loaded_content):
        fuente = content.get("source", "desconocido") if content else "sin_contenido"
        report_html = content.get("report_html") if content else None
        annex.append(
            {
                "circuito": record["circuito"],
                "criticidad": record.get("criticidad"),
                "fuente": fuente,
                "resumen": _annex_summary_lines(content),
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
        f"Los {n} circuitos son los de mayor conteo de vanos en Medio-Alto + Alto dentro "
        f"de la banda, es decir su cola más crítica; no describen la banda completa.",
    ]

    total_uiti = sum(record["uiti_total"] for record in sampled_records)
    total_criticos = sum(record["vanos_criticos"] for record in sampled_records)
    items.append(
        f"La muestra suma {total_criticos:,} vanos en Medio-Alto + Alto y "
        f"{total_uiti:,.2f} unidades de UITI_VANO acumulado en la ventana analizada."
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
        top_record = max(sampled_records, key=lambda record: record["vanos_criticos"])
        items.append(
            f"El circuito peor situado de la muestra es {top_record['circuito']}: puesto "
            f"{top_record['posicion']} de la flota, con {top_record['vanos_criticos']:,} vanos "
            f"en Medio-Alto + Alto y {top_record['uiti_total']:,.2f} de UITI_VANO acumulado."
        )

    conditional: list[str] = []
    if outliers:
        names = ", ".join(item["circuito"] for item in outliers)
        conditional.append(
            f"Se identificaron {len(outliers)} circuito(s) atípico(s) ({names}) con desviación "
            "marcada en UITI_VANO o en eventos por vano respecto a la mediana muestral."
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
    (`sampled_records`, one dict per circuit with `vanos_criticos`,
    `uiti_total`, `eventos_total`, `criticidad`, `posicion`) and their loaded content
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


INTERVENTION_SUMMARY_SCHEMA_VERSION = "informe-gerencial-grafo-intervencion/v1"


def _intervention_summary_path(graph_intervencion_path: str | Path | None) -> Path | None:
    """Mirror of `intervention_graph.summary_path`, kept here rather than
    imported for the same cycle reason `load_intervention_summary` documents.
    A test pins the two against each other so they cannot drift.
    """
    if graph_intervencion_path is None:
        return None
    destination = Path(graph_intervencion_path)
    return destination.with_suffix(destination.suffix + ".resumen.json")


def load_intervention_summary(path: str | Path | None) -> dict[str, Any] | None:
    """Load the causes/strategies summary `intervention_graph build` writes
    beside its HTML figure (`<figura>.resumen.json`).

    File handoff rather than an import: `intervention_graph` already imports
    THIS module, so importing it back would close a cycle. Pure I/O, never
    raises (threat matrix: path injection via `--graph-intervencion`):
    missing/unreadable/malformed -> `None`.
    """
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("causas"), list) or not isinstance(payload.get("estrategias"), list):
        return None
    return payload


def _cuerpo_html(documento: str | None) -> str:
    """El contenido de `<body>`, o el texto tal cual si ya es un fragmento.

    El constructor del grafo escribe una PAGINA completa -- tambien se abre suelta --,
    y meter un `<!DOCTYPE html>` dentro de otro documento es HTML invalido: el navegador
    lo repara como puede y el resultado depende de cual sea. Se recorta al cuerpo.

    Lo que se pierde por el camino es el `<script>` de `plotly.js` que esa pagina trae en
    su cabeza; por eso el informe lo carga por su cuenta y no colgando de una figura.
    """
    if not documento:
        return ""
    texto = str(documento)
    inicio = texto.lower().find("<body")
    if inicio < 0:
        return texto
    inicio = texto.find(">", inicio)
    fin = texto.lower().rfind("</body>")
    if inicio < 0 or fin < 0:
        return texto
    return texto[inicio + 1:fin]


def _intervention_graph_html(
    graph_intervencion_html: str | None,
    summary: dict[str, Any] | None,
    *,
    n_sampled: int,
) -> str:
    """Render the "Causas y estrategias de intervención" section: the radial
    figure plus the same causes/strategies written out as text.

    Deliberately INDEPENDENT of the graph-patterns section below it. The two
    answer different questions from different sources, and coupling them (as
    the previous dual-graph toggle did) meant a failed `graphify` rebuild also
    took down a figure that never needed `graphify` in the first place. Omitted
    entirely when fewer than 2 circuits were sampled, or when the builder
    produced nothing this run -- there is no muted placeholder, because a
    section that only ever says "not available" is noise in a managerial
    report.
    """
    if n_sampled < 2 or not graph_intervencion_html:
        return ""

    badge = (
        '<p class="badge-agentes">Síntesis de los agentes '
        "(histórico + alineamiento experto)</p>"
    )
    bloques = [badge]
    if summary:
        causas = summary.get("causas") or []
        estrategias = summary.get("estrategias") or []
        if causas:
            filas = "".join(
                f"<li><strong>{_escape(item.get('concepto'))}</strong> &mdash; "
                f"{_escape(item.get('soporte'))} de {n_sampled} circuitos</li>"
                for item in causas
            )
            bloques.append(f"<h3>Causas compartidas</h3><ul>{filas}</ul>")
        if estrategias:
            filas = "".join(
                f"<li><strong>{_escape(item.get('concepto'))}</strong> &mdash; "
                f"{_escape(item.get('soporte'))} de {n_sampled} circuitos, "
                f"prioridad {_escape(item.get('prioridad') or 'sin definir')}</li>"
                for item in estrategias
            )
            bloques.append(f"<h3>Estrategias de intervención propuestas</h3><ul>{filas}</ul>")
    # INLINE y ya no dentro de un iframe. El iframe hacia falta cuando el grafo era una
    # pagina de `vis-network` con su propio panel lateral y su buscador; en Plotly es un
    # `<div>` que se basta solo. Y el iframe cobraba: su contenido no hereda la hoja de
    # estilos del informe ni el `plotly.js` que la pagina ya carga para el
    # dispersograma, y no crece con el ancho de la pagina.
    bloques.append(f'<div class="grafo-conceptos">{_cuerpo_html(graph_intervencion_html)}</div>')

    cuerpo = "\n".join(bloques)
    return f"""
<section class="report-section">
<h2>Causas y estrategias de intervención</h2>
{cuerpo}
</section>
"""


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
    the itemized list itself is populated, the embedded community figure
    (`graph_view_html`), or a muted "not available this run" indicator when
    that figure failed to build (independent degradation from the list
    itself).

    The radial causes/strategies figure USED to share this section behind a
    toggle; it now has its own (`_intervention_graph_html`) because it no
    longer comes from `graphify` and must not degrade with it.
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
        body += (
            _iframe_srcdoc(graph_view_html)
            if graph_view_html
            else "<p class='muted'>figura de grafo no disponible en esta corrida.</p>"
        )

    return f"""
<section class="report-section">
<h2>Patrones cross-circuito (grafo)</h2>
{badge}
{body}
</section>
"""


def _resumen_item_html(item: str | dict[str, Any]) -> str:
    """Render one `resumen` entry: a plain string as a single `<li>`, or the
    cause-hypothesis dict (`{"label": ..., "items": [...]}` from
    `_annex_summary_lines`) as a labeled `<li>` with a nested sub-list, one
    `<li>` per clause -- so the annex table shows the hypothesis as scannable
    sub-items rather than one dense paragraph, consistently on every run.
    """
    if isinstance(item, dict):
        label = _escape(item.get("label"))
        sub_items = "".join(f"<li>{_escape(sub)}</li>" for sub in item.get("items") or [])
        return f"<li>{label}<ul class='annex-subitems'>{sub_items}</ul></li>"
    return f"<li>{_escape(item)}</li>"


def _annex_html(annex: Sequence[dict[str, Any]]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_escape(entry['circuito'])}</td>"
        f"<td>{_escape(entry.get('criticidad'))}</td>"
        f"<td>{_report_reference_html(entry.get('report_html'))}</td>"
        f"<td><ul class='annex-summary'>"
        f"{''.join(_resumen_item_html(line) for line in entry['resumen'])}"
        f"</ul></td>"
        "</tr>"
        for entry in annex
    )
    return (
        "<table class='annex-table'><thead><tr>"
        "<th>Circuito</th><th>Criticidad</th><th>Informe del circuito</th><th>Hallazgos principales</th>"
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


# Lo COMPARTIDO -- tipografia, marco, encabezados, tablas, escudo y pie -- se inyecta
# desde `informe_estilo`, no se copia: dos hojas escritas por separado es exactamente
# como estos dos informes se separaron. Aqui abajo queda solo lo PROPIO del gerencial.
_REPORT_CSS = CSS_IDENTIDAD + """
/* La tabla de ventanas y el grafo de conceptos. */
.tabla-ventanas { width: 100%; border-collapse: collapse; font-size: .9rem; margin-top: 12px; }
.tabla-ventanas th, .tabla-ventanas td { border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; }
.tabla-ventanas th { background: #f8fafc; color: #1e3a8a; }
.grafo-conceptos { border: 1px solid #e2e8f0; border-radius: 8px; background: #ffffff; padding: 8px; }
.grafo-conceptos .plotly-graph-div { width: 100% !important; }
.meta { color: #475569; }
.report-section { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; margin: 16px 0; }
.muted { color: #94a3b8; font-style: italic; }
.annex-table { width: 100%; border-collapse: collapse; }
.annex-table th, .annex-table td { border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; font-size: 0.9rem; vertical-align: top; }
.annex-summary { margin: 0; padding-left: 1.1rem; }
.annex-summary li { margin: 2px 0; }
.annex-subitems { margin: 4px 0 2px; padding-left: 1.1rem; list-style-type: circle; }
.annex-subitems li { margin: 2px 0; color: #334155; }
.badge-llm { display: inline-block; background: #ede9fe; color: #5b21b6; border-radius: 999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; margin: 0 0 8px; }
.badge-deterministic { display: inline-block; background: #dcfce7; color: #166534; border-radius: 999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; margin: 0 0 8px; }
.badge-agentes { display: inline-block; background: #dbeafe; color: #1e40af; border-radius: 999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; margin: 0 0 8px; }
.report-section h3 { font-size: 0.95rem; color: #334155; margin: 14px 0 4px; }
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
    graph_intervencion_html: str | None = None,
    intervention_summary: dict[str, Any] | None = None,
) -> str:
    """Renderiza el unico HTML del informe -- resumen/patrones/atipicos/riesgo/acciones
    mas las barras del RANKING de la flota entera, con solo los `sampled` resaltados.

    La figura reusa `plot_ranking_circuitos(raw_df, ...)` TAL CUAL contra el `raw_df`
    completo y sin filtrar: siguen apareciendo los 208 circuitos y las cuatro bandas,
    nunca se esconde nada, y los muestreados se marcan con el borde.

    Antes aqui iba la nube de K-Means (`plot_interactive_circuit_clustering`). Se cambio
    porque el informe pasó a agrupar por el ranking: la nube situaba al circuito por
    TAMANO -- eventos contra UITI acumulado -- y sus cinco clases no eran las cuatro
    bandas por las que el informe estaba agrupando. El lector veia una figura que no
    podia explicar el grupo del que hablaba el texto. Es el mismo arreglo que
    `context_builder` ya habia hecho para el informe por circuito.
    """
    fig = plot_ranking_circuitos(
        raw_df,
        list(sampled),
        resolved_window.get("fecha_inicio"),
        resolved_window.get("fecha_fin"),
    )
    # `plotly.js` UNA vez y en la cabeza, no colgando del dispersograma: el grafo de
    # conceptos va INLINE y se quedaria sin motor si esta figura faltara. Es el mismo
    # fallo que ya se corrigio en el informe por circuito.
    scatter_html = fig.to_html(full_html=False, include_plotlyjs=False) if fig else ""

    label = group.get("label") or group.get("slug") or "grupo"
    circuit_count = group.get("circuit_count", len(sampled))
    intervention_section_html = _intervention_graph_html(
        graph_intervencion_html, intervention_summary, n_sampled=len(sampled)
    )
    # La concentracion por VENTANA. Va antes de las causas: primero cuando pasa, y
    # despues por que. Determinista, de los sobres que `prepare` dejo en disco.
    ventanas_section_html = _ventanas_html(ventanas_del_grupo(sampled))
    graph_section_html = _graph_patterns_html(
        graph_patterns, graph_view_html, n_sampled=len(sampled)
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe Gerencial: Circuitos en {_escape(label)}</title>
<style>{_REPORT_CSS}</style>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
</head>
<body>
<div class="container">
{escudo_chec_html()}
<h1>Informe Gerencial: Circuitos en {_escape(label)}</h1>
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
{ventanas_section_html}{intervention_section_html}{graph_section_html}
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
{pie_agentes_html()}
</div>
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
    graph_intervencion_path: str | Path | None = None,
) -> InformeGerencialOutcome:
    """Full render pipeline: re-resolve the SAME deterministic group/window/
    sampling as `resolve()` (K-Means is seeded, so the sampled set is
    reproducible), load each sampled circuit's content, synthesize, render,
    and persist the HTML report.

    `graph_intervencion_path` (the `intervention_graph build` figure) is loaded
    via the SAME `load_graph_view` reused for `graph_view_path` -- both are
    raw, pre-rendered HTML text with an identical never-raise degrade
    contract, so no new loader is needed. Its sibling
    `<figura>.resumen.json` is read alongside it, so the section can also
    NAME the causes and strategies instead of only drawing them.

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
            # Los numeros del RANKING. Ojo con `eventos_total`: es la suma de los eventos
            # de cada vano del circuito, la unidad de este tablero. NO es el conteo de
            # fechas distintas que usaba el K-Means de circuitos -- una misma salida
            # golpea muchos vanos y ahi contaba una sola vez --, asi que los dos numeros
            # no son comparables entre corridas viejas y nuevas.
            "vanos_criticos": int(row["vanos_criticos"]),
            "vanos_medio_alto": int(row["vanos_medio_alto"]),
            "vanos_alto": int(row["vanos_alto"]),
            "vanos_con_eventos": int(row["vanos_con_eventos"]),
            "uiti_total": float(row["uiti_total"]),
            "eventos_total": int(row["eventos_total"]),
            "criticidad": row["criticidad"],
            "posicion": int(row["posicion"]),
        }
        for circuito, row in sampled_df.iterrows()
    ]
    sampled = [record["circuito"] for record in sampled_records]

    loaded_content = [
        load_circuit_content(circuito, runs_root=runs_root, vault_root=vault_root) for circuito in sampled
    ]
    graph_patterns = load_graph_patterns(graph_patterns_path, sampled)
    graph_view_html = load_graph_view(graph_view_path)
    graph_intervencion_html = load_graph_view(graph_intervencion_path)
    intervention_summary = load_intervention_summary(
        _intervention_summary_path(graph_intervencion_path)
    )

    synthesis = synthesize(sampled_records, loaded_content, group)
    html = render_managerial_report(
        frame,
        synthesis=synthesis,
        group=group,
        resolved_window=resolved_window,
        sampled=sampled,
        graph_patterns=graph_patterns,
        graph_view_html=graph_view_html,
        graph_intervencion_html=graph_intervencion_html,
        intervention_summary=intervention_summary,
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
    render_command.add_argument("--graph-intervencion")

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
            graph_intervencion_path=args.graph_intervencion,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status == "success" else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
