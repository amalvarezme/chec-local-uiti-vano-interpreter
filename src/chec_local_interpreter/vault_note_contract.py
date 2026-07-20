"""Pure per-circuit vault-note projection contract.

Sibling of `circuit_clustering_contract.py` / `batch_report_contract.py`:
those modules render a chart / resolve a batch group, this one projects the
3 already-validated per-run narrative JSONs (`historical.out.json`,
`inference.out.json`, `expert-alignment.out.json`) written by a completed
`/report` run into one compact, upserted Spanish markdown note per circuit
at `reports/vault/{circuito}.md`.

This module performs NO LLM calls and NO subprocess/shell invocations -- it
only reads already-written `*.out.json` files and writes markdown. The
`/graphify reports/vault --update` chaining that follows a successful write
is an orchestrator-level (runbook) concern, not something this module ever
shells out to (see design decision "How `/graphify` is invoked"). That
chained update is scoped to an isolated graph rooted at
`reports/vault/graphify-out/graph.json`, never the project-root
`graphify-out/graph.json` -- see `vault-circuito/SKILL.md` step 2.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.config import PROJECT_ROOT

SCHEMA_VERSION = "vault-note-contract/v1"

DEFAULT_RUNS_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "runs"
DEFAULT_VAULT_ROOT = PROJECT_ROOT / "reports" / "vault"

HISTORICAL_FILENAME = "historical.out.json"
INFERENCE_FILENAME = "inference.out.json"
EXPERT_ALIGNMENT_FILENAME = "expert-alignment.out.json"

_MISSING_SECTION_NOTE = "> Sección no disponible en esta corrida."

VaultStatus = Literal[
    "success",
    "partial",
    "skipped_incomplete",
    "usage_error",
    "execution_error",
]


# ---------------------------------------------------------------------------
# find_latest_run
# ---------------------------------------------------------------------------


def find_latest_run(circuito: str, *, runs_root: str | Path | None = None) -> Path | None:
    """Return the latest (max-timestamp) run dir for `circuito`, or `None`.

    Run dirs use `%Y%m%dT%H%M%S%f` timestamps (see `report_pipeline._new_run_dir`),
    which are lexicographically sortable -- so a plain max-by-name over the
    immediate subdirectories always picks the newest run without parsing.
    """
    root = Path(runs_root) if runs_root is not None else DEFAULT_RUNS_ROOT
    circuit_dir = root / canonical_circuit_identity(circuito)
    if not circuit_dir.is_dir():
        return None
    run_dirs = [entry for entry in circuit_dir.iterdir() if entry.is_dir()]
    if not run_dirs:
        return None
    return max(run_dirs, key=lambda entry: entry.name)


# ---------------------------------------------------------------------------
# load_run_narratives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunNarratives:
    status: Literal["success", "partial", "skipped_incomplete"]
    historical: dict[str, Any] | None = None
    inference: dict[str, Any] | None = None
    expert_alignment: dict[str, Any] | None = None
    missing_files: list[str] = field(default_factory=list)


def _load_ok_data(path: Path) -> dict[str, Any] | None:
    """Return the `data` payload of a `*.out.json` file iff `ok` is true.

    Returns `None` (never raises) for: file missing, invalid JSON, malformed
    payload, or `ok: false` -- callers decide whether that `None` is fatal
    (historical) or degrades to a placeholder section (inference /
    expert-alignment). This is what keeps `load_run_narratives` itself
    never-raising, matching the spec's alert-and-skip requirement.
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def load_run_narratives(run_dir: Path) -> RunNarratives:
    """Load the 3 per-run narrative JSONs from `run_dir`.

    `historical.out.json` (with `ok: true`) is REQUIRED -- its absence or
    `ok: false` short-circuits to `skipped_incomplete` with no further reads.
    `inference.out.json` and `expert-alignment.out.json` are OPTIONAL --
    missing either downgrades the result to `partial`, never to a skip.
    """
    historical = _load_ok_data(run_dir / HISTORICAL_FILENAME)
    if historical is None:
        return RunNarratives(status="skipped_incomplete", missing_files=[HISTORICAL_FILENAME])

    inference = _load_ok_data(run_dir / INFERENCE_FILENAME)
    expert_alignment = _load_ok_data(run_dir / EXPERT_ALIGNMENT_FILENAME)

    missing: list[str] = []
    if inference is None:
        missing.append(INFERENCE_FILENAME)
    if expert_alignment is None:
        missing.append(EXPERT_ALIGNMENT_FILENAME)

    return RunNarratives(
        status="partial" if missing else "success",
        historical=historical,
        inference=inference,
        expert_alignment=expert_alignment,
        missing_files=missing,
    )


# ---------------------------------------------------------------------------
# render_vault_markdown
# ---------------------------------------------------------------------------


def _format_evidence_bullets(evidence: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in evidence:
        date = item.get("date", "")
        critical_point_id = item.get("critical_point_id", "")
        summary = item.get("summary", "")
        lines.append(f"  - {date} ({critical_point_id}): {summary}")
    return lines


def _render_key_findings(key_findings: list[dict[str, Any]]) -> list[str]:
    lines = ["### Hallazgos clave", ""]
    if not key_findings:
        lines.append(_MISSING_SECTION_NOTE)
        lines.append("")
        return lines
    for finding in key_findings:
        title = finding.get("title", "")
        confidence = finding.get("confidence", "")
        text = finding.get("text", "")
        lines.append(f"- **{title}** (confianza: {confidence})")
        lines.append(f"  {text}")
        lines.extend(_format_evidence_bullets(finding.get("evidence") or []))
        lines.append("")
    return lines


def _render_characterization(characterization: dict[str, Any]) -> list[str]:
    lines = ["### Caracterización", ""]
    text = characterization.get("text", "")
    if text:
        lines.append(text)
        lines.append("")
    p97_uiti = characterization.get("p97_vanos_uiti_vano") or []
    p97_eventos = characterization.get("p97_vanos_eventos") or []
    if p97_uiti:
        lines.append("**Percentil 97 por UITI_VANO:** " + ", ".join(p97_uiti))
    if p97_eventos:
        lines.append("**Percentil 97 por eventos:** " + ", ".join(p97_eventos))
    lines.append("")
    return lines


def _render_bullet_list(title: str, items: list[str]) -> list[str]:
    lines = [title, ""]
    if not items:
        lines.append(_MISSING_SECTION_NOTE)
    else:
        lines.extend(f"- {item}" for item in items)
    lines.append("")
    return lines


def _render_historical_section(historical: dict[str, Any]) -> list[str]:
    lines = ["## Resumen histórico", ""]
    headline = historical.get("headline", "")
    if headline:
        lines.append(f"**{headline}**")
        lines.append("")
    for bullet in historical.get("executive_summary") or []:
        lines.append(f"- {bullet}")
    lines.append("")
    lines.extend(_render_key_findings(historical.get("key_findings") or []))
    lines.extend(_render_characterization(historical.get("circuit_characterization") or {}))
    lines.append("### Síntesis del período")
    lines.append("")
    lines.append(historical.get("period_synthesis") or _MISSING_SECTION_NOTE)
    lines.append("")
    lines.append("### Hipótesis de causa")
    lines.append("")
    lines.append(historical.get("cause_hypothesis_note") or _MISSING_SECTION_NOTE)
    lines.append("")
    lines.extend(_render_bullet_list("### Vacíos de datos", historical.get("data_gaps") or []))
    lines.extend(_render_bullet_list("### Acciones recomendadas", historical.get("recommended_actions") or []))
    return lines


def _render_inference_section(inference: dict[str, Any] | None) -> list[str]:
    lines = ["## Interpretación inferencial", ""]
    if inference is None:
        lines.append(_MISSING_SECTION_NOTE)
        lines.append("")
        return lines
    contexto = inference.get("contexto") or {}
    modelo = contexto.get("modelo")
    if modelo:
        lines.append(f"Modelo: {modelo}")
        lines.append("")
    for escenario in inference.get("escenarios") or []:
        nombre = escenario.get("nombre", "")
        interpretacion = escenario.get("interpretacion", "")
        lines.append(f"### {nombre}")
        lines.append("")
        lines.append(interpretacion)
        lines.append("")
    return lines


def _render_expert_alignment_section(expert_alignment: dict[str, Any] | None) -> list[str]:
    lines = ["## Alineación con experto", ""]
    if expert_alignment is None:
        lines.append(_MISSING_SECTION_NOTE)
        lines.append("")
        return lines
    coincidencias = expert_alignment.get("coincidencias") or []
    if not coincidencias:
        razon = (expert_alignment.get("contexto") or {}).get("modelo_experto_razon", "")
        lines.append(razon or _MISSING_SECTION_NOTE)
        lines.append("")
        return lines
    for item in coincidencias:
        tema = item.get("tema", "")
        fuentes = item.get("fuentes") or []
        explicacion = item.get("explicacion", "")
        lines.append(f"- **{tema}** ({', '.join(fuentes)}): {explicacion}")
    lines.append("")
    return lines


def _resolve_ventana(
    inference: dict[str, Any] | None, expert_alignment: dict[str, Any] | None
) -> str | None:
    for section in (inference, expert_alignment):
        if not section:
            continue
        periodo = (section.get("contexto") or {}).get("periodo") or {}
        inicio, fin = periodo.get("inicio"), periodo.get("fin")
        if inicio and fin:
            return f"{inicio} a {fin}"
    return None


def render_vault_markdown(circuito: str, run_id: str, narratives: RunNarratives) -> str:
    """Render the full vault note markdown for `circuito` from `narratives`.

    `narratives.historical` is REQUIRED -- callers (`render`) must only ever
    invoke this once `load_run_narratives` returned `success`/`partial`
    (never `skipped_incomplete`); this guard exists to make that precondition
    loud instead of silently emitting a headline-less note.
    """
    if narratives.historical is None:
        raise ValueError("render_vault_markdown requires historical narrative data")

    lines = [f"# {circuito}", ""]
    ventana = _resolve_ventana(narratives.inference, narratives.expert_alignment)
    banner = f"> Nota generada automáticamente. Corrida: `{run_id}`."
    if ventana:
        banner += f" Ventana: {ventana}."
    lines.append(banner)
    lines.append("")
    lines.extend(_render_historical_section(narratives.historical))
    lines.extend(_render_inference_section(narratives.inference))
    lines.extend(_render_expert_alignment_section(narratives.expert_alignment))
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# write_vault_note
# ---------------------------------------------------------------------------


def write_vault_note(circuito: str, markdown: str, *, vault_root: str | Path | None = None) -> Path:
    """Upsert-write `markdown` to `reports/vault/{canonical circuito}.md`.

    Threat-matrix mitigation (vault filename path traversal): the filename is
    derived exclusively from `canonical_circuit_identity`, then the resolved
    target path is additionally verified to remain a direct child of the
    resolved vault root, using the same `resolve()` + `relative_to()` guard
    idiom as `cleanup_runs._resolve_category_root`.
    """
    root = Path(vault_root) if vault_root is not None else DEFAULT_VAULT_ROOT
    resolved_root = root.resolve()
    filename = f"{canonical_circuit_identity(circuito)}.md"
    target = (root / filename).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing vault note path {target} outside vault root {resolved_root}"
        ) from exc
    atomic_write_text(target, markdown)
    return target


# ---------------------------------------------------------------------------
# VaultOutcome + render() + CLI
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VaultOutcome:
    status: VaultStatus
    circuito: str | None = None
    run_id: str | None = None
    vault_note_path: str | None = None
    missing_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "circuito": self.circuito,
            "run_id": self.run_id,
            "vault_note_path": self.vault_note_path,
            "missing_files": list(self.missing_files),
            "errors": list(self.errors),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)


def usage_error(message: str, circuito: str | None = None) -> VaultOutcome:
    return VaultOutcome(status="usage_error", circuito=circuito, errors=[message])


def render(
    circuito: str,
    *,
    runs_root: str | Path | None = None,
    vault_root: str | Path | None = None,
) -> VaultOutcome:
    """End-to-end projection for `circuito`: find latest run, load its 3
    narrative JSONs, render markdown, upsert-write it. Never raises for
    missing/partial data -- alert-and-skip is expressed via `VaultOutcome`.
    """
    run_dir = find_latest_run(circuito, runs_root=runs_root)
    if run_dir is None:
        return VaultOutcome(
            status="skipped_incomplete",
            circuito=circuito,
            errors=[f"No runs found for circuito {circuito!r}"],
        )

    narratives = load_run_narratives(run_dir)
    if narratives.status == "skipped_incomplete":
        return VaultOutcome(
            status="skipped_incomplete",
            circuito=circuito,
            run_id=run_dir.name,
            missing_files=narratives.missing_files,
            errors=[f"Missing required file(s): {', '.join(narratives.missing_files)}"],
        )

    markdown = render_vault_markdown(circuito, run_dir.name, narratives)
    target = write_vault_note(circuito, markdown, vault_root=vault_root)
    return VaultOutcome(
        status=narratives.status,
        circuito=circuito,
        run_id=run_dir.name,
        vault_note_path=str(target),
        missing_files=narratives.missing_files,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.vault_note_contract")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_command = subparsers.add_parser("render")
    render_command.add_argument("circuito")
    render_command.add_argument("--runs-root")
    render_command.add_argument("--vault-root")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "render":
        circuito = (args.circuito or "").strip()
        if not circuito:
            outcome = usage_error("circuito is required")
            print(outcome.to_json_text())
            return 2
        outcome = render(circuito, runs_root=args.runs_root, vault_root=args.vault_root)
        print(outcome.to_json_text())
        return 0 if outcome.status in ("success", "partial", "skipped_incomplete") else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
