"""Shared runtime contract for `/reporte-lote` -- batch `/report` by circuit-criticality group.

Sibling of `circuit_clustering_contract.py`: that module renders ONE
clustering chart to HTML, this one resolves a criticality-group slug (or
`todos`) to a circuit list plus a shared dataset-wide date window, and
persists the batch-run manifest once the loop that consumes this contract
(`.claude/skills/reporte-lote/SKILL.md`) has finished running every circuit.

The dataset-wide window resolution is REUSED, not reimplemented: it imports
`_dataset_date_range` from `circuit_clustering_contract` so both contracts
can never drift on what "the full dataset range" means.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence

from chec_local_interpreter.agent_output import ReportPipelineError
from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text
from chec_local_interpreter.circuit_clustering_contract import RuntimeMetadata, _dataset_date_range
from chec_local_interpreter.config import DEFAULT_DATA_PATH, PROJECT_ROOT
from chec_local_interpreter.data_loader import available_circuits, filter_events, load_dataset
from chec_local_interpreter.plotting import CRITICALITY_GROUP_LABELS, compute_circuit_criticality_groups

SCHEMA_VERSION = "batch-report-contract/v1"

# Drift-proof by construction: zipped against CRITICALITY_GROUP_LABELS so the
# CLI slug vocabulary can never fall out of sync with the shared clustering
# helper's tier ordering.
GROUP_SLUGS: tuple[str, ...] = ("muy-alta", "alta", "media", "baja", "muy-baja")
GROUP_SLUG_TO_LABEL: dict[str, str] = dict(zip(GROUP_SLUGS, CRITICALITY_GROUP_LABELS))
ALL_GROUPS_SLUG = "todos"
VALID_GROUP_SLUGS: tuple[str, ...] = (*GROUP_SLUGS, ALL_GROUPS_SLUG)

DEFAULT_RUNS_ROOT = PROJECT_ROOT / "reports" / "interpretability" / "runs" / "_batch"

_SAFE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

BatchStatus = Literal[
    "awaiting_confirmation",
    "empty_group",
    "usage_error",
    "execution_error",
]


@dataclass(frozen=True)
class BatchReportRequest:
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
class BatchReportOutcome:
    status: BatchStatus
    request: BatchReportRequest | None = None
    resolved_window: dict[str, Any] | None = None
    group: dict[str, Any] | None = None
    next_actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "request": self.request.to_json() if self.request else None,
            "resolved_window": self.resolved_window,
            "group": self.group,
            "next_actions": list(self.next_actions),
            "errors": list(self.errors),
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
) -> BatchReportRequest:
    if grupo not in VALID_GROUP_SLUGS:
        raise ValueError(
            f"grupo desconocido: {grupo!r}. Opciones: {', '.join(VALID_GROUP_SLUGS)}"
        )
    if (fecha_inicio is None) != (fecha_fin is None):
        raise ValueError(
            "fecha_inicio and fecha_fin must be provided together or both omitted"
        )
    return BatchReportRequest(
        grupo=grupo,
        criticidad=GROUP_SLUG_TO_LABEL.get(grupo),
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        runtime=RuntimeMetadata(runtime=runtime, provider=provider, model=model),
    )


def usage_error(message: str, request: BatchReportRequest | None = None) -> BatchReportOutcome:
    return BatchReportOutcome(status="usage_error", request=request, errors=[message])


def preflight_batch(
    request: BatchReportRequest, *, data_path: str | Path | None = None
) -> BatchReportOutcome:
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

        if request.grupo == ALL_GROUPS_SLUG:
            circuitos = available_circuits(filtered)
        else:
            df_coords = compute_circuit_criticality_groups(filtered)
            circuitos = df_coords[df_coords["criticidad"] == request.criticidad].index.tolist()
    except (FileNotFoundError, ValueError, ReportPipelineError) as exc:
        return BatchReportOutcome(status="execution_error", request=request, errors=[str(exc)])

    group = {
        "slug": request.grupo,
        "label": request.criticidad,
        "circuit_count": len(circuitos),
        "circuitos": circuitos,
    }
    resolved_window = {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin}

    if not circuitos:
        return BatchReportOutcome(
            status="empty_group",
            request=request,
            resolved_window=resolved_window,
            group=group,
        )

    return BatchReportOutcome(
        status="awaiting_confirmation",
        request=request,
        resolved_window=resolved_window,
        group=group,
        next_actions=["confirm_batch"],
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def _safe_manifest_path(runs_root: Path, *, grupo: str, fecha_inicio: str, fecha_fin: str) -> Path:
    """Build the manifest path from allowlisted, format-validated inputs only.

    `grupo` must be one of `VALID_GROUP_SLUGS` and both dates must match
    `YYYY-MM-DD` -- this forecloses path traversal via any of the three
    values that end up in the filename (threat-matrix: manifest path
    injection).
    """
    if grupo not in VALID_GROUP_SLUGS:
        raise ValueError(f"grupo desconocido: {grupo!r}. Opciones: {', '.join(VALID_GROUP_SLUGS)}")
    if not _SAFE_DATE_RE.match(fecha_inicio) or not _SAFE_DATE_RE.match(fecha_fin):
        raise ValueError("fecha_inicio/fecha_fin must be ISO dates (YYYY-MM-DD)")
    filename = f"reporte-lote__{grupo}__{fecha_inicio}__{fecha_fin}__{_utc_timestamp()}.json"
    return runs_root / filename


def write_manifest(
    entries: list[dict[str, Any]],
    *,
    grupo: str,
    criticidad: str | None,
    fecha_inicio: str,
    fecha_fin: str,
    runs_root: str | Path | None = None,
) -> dict[str, Any]:
    target_root = Path(runs_root) if runs_root is not None else DEFAULT_RUNS_ROOT
    target = _safe_manifest_path(target_root, grupo=grupo, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)
    manifest = {
        "tool_version": SCHEMA_VERSION,
        "generated_at": _utc_timestamp(),
        "grupo": grupo,
        "criticidad": criticidad,
        "fecha_inicio": fecha_inicio,
        "fecha_fin": fecha_fin,
        "circuits": list(entries),
    }
    atomic_write_text(target, json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"status": "success", "manifest_path": str(target)}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m chec_local_interpreter.batch_report_contract"
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

    preflight_command = subparsers.add_parser("preflight")
    add_request_args(preflight_command)
    preflight_command.add_argument("--data-path")

    write_manifest_command = subparsers.add_parser("write-manifest")
    write_manifest_command.add_argument("--grupo", required=True)
    write_manifest_command.add_argument("--criticidad")
    write_manifest_command.add_argument("--fecha-inicio", required=True)
    write_manifest_command.add_argument("--fecha-fin", required=True)
    write_manifest_command.add_argument("--runs-root")

    return parser


def _request_from_args(args: argparse.Namespace) -> BatchReportRequest:
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

    if args.command == "write-manifest":
        try:
            entries = json.loads(sys.stdin.read())
            if not isinstance(entries, list):
                raise ValueError("write-manifest expects a JSON array of entries on stdin")
            result = write_manifest(
                entries,
                grupo=args.grupo,
                criticidad=args.criticidad,
                fecha_inicio=args.fecha_inicio,
                fecha_fin=args.fecha_fin,
                runs_root=args.runs_root,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            print(usage_error(str(exc)).to_json_text())
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    try:
        request = _request_from_args(args)
    except ValueError as exc:
        print(usage_error(str(exc)).to_json_text())
        return 2

    if args.command == "parse":
        print(
            BatchReportOutcome(
                status="awaiting_confirmation",
                request=request,
                next_actions=["confirm_batch"],
            ).to_json_text()
        )
        return 0
    if args.command == "preflight":
        outcome = preflight_batch(request, data_path=args.data_path)
        print(outcome.to_json_text())
        return 0 if outcome.status == "awaiting_confirmation" else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
