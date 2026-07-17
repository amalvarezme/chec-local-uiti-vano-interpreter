"""Shared runtime contract for the standalone circuit-clustering chart."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

import pandas as pd

from chec_local_interpreter.agent_output import ReportPipelineError
from chec_local_interpreter.config import DEFAULT_DATA_PATH, DEFAULT_OUTPUT_DIR
from chec_local_interpreter.data_loader import filter_events, load_dataset, parse_fecha

SCHEMA_VERSION = "circuit-clustering-contract/v1"
UNKNOWN_MODEL_LABEL = "Desconocido"
DEFAULT_OUTPUT_ROOT = DEFAULT_OUTPUT_DIR / "agrupamiento-circuitos"

ClusteringStatus = Literal[
    "awaiting_confirmation",
    "success",
    "usage_error",
    "execution_error",
]


@dataclass(frozen=True)
class RuntimeMetadata:
    runtime: str | None = None
    provider: str | None = None
    model: str | None = None

    @property
    def model_known(self) -> bool:
        return bool(self.model)

    def to_json(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "provider": self.provider,
            "model": self.model if self.model else UNKNOWN_MODEL_LABEL,
            "model_known": self.model_known,
        }


@dataclass(frozen=True)
class ClusteringRequest:
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    runtime: RuntimeMetadata = field(default_factory=RuntimeMetadata)

    def to_json(self) -> dict[str, Any]:
        return {
            "fecha_inicio": self.fecha_inicio,
            "fecha_fin": self.fecha_fin,
            "runtime": self.runtime.to_json(),
        }


@dataclass(frozen=True)
class ClusteringOutcome:
    status: ClusteringStatus
    request: ClusteringRequest | None = None
    resolved_window: dict[str, Any] | None = None
    output_html: str | None = None
    next_actions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "request": self.request.to_json() if self.request else None,
            "resolved_window": self.resolved_window,
            "output_html": self.output_html if self.status == "success" else None,
            "next_actions": list(self.next_actions),
            "errors": list(self.errors),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)


def normalize_request(
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    *,
    runtime: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> ClusteringRequest:
    if (fecha_inicio is None) != (fecha_fin is None):
        raise ValueError(
            "fecha_inicio and fecha_fin must be provided together or both omitted"
        )
    return ClusteringRequest(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        runtime=RuntimeMetadata(runtime=runtime, provider=provider, model=model),
    )


def usage_error(message: str, request: ClusteringRequest | None = None) -> ClusteringOutcome:
    return ClusteringOutcome(status="usage_error", request=request, errors=[message])


def plot_interactive_circuit_clustering(*args, **kwargs):
    from chec_local_interpreter.plotting import (
        plot_interactive_circuit_clustering as _plot_interactive_circuit_clustering,
    )

    return _plot_interactive_circuit_clustering(*args, **kwargs)


def _dataset_date_range(frame: pd.DataFrame) -> tuple[str | None, str | None]:
    fechas = parse_fecha(frame).dropna()
    if fechas.empty:
        return None, None
    return fechas.min().date().isoformat(), fechas.max().date().isoformat()


def _resolve_window(
    request: ClusteringRequest, *, data_path: str | Path | None = None
) -> tuple[pd.DataFrame, str, str, int]:
    source_path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
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
    return frame, fecha_inicio, fecha_fin, int(len(filtered))


def preflight_clustering(
    request: ClusteringRequest, *, data_path: str | Path | None = None
) -> ClusteringOutcome:
    try:
        _, fecha_inicio, fecha_fin, event_count = _resolve_window(request, data_path=data_path)
    except (FileNotFoundError, ValueError, ReportPipelineError) as exc:
        return ClusteringOutcome(status="execution_error", request=request, errors=[str(exc)])
    return ClusteringOutcome(
        status="awaiting_confirmation",
        request=request,
        resolved_window={
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "event_count": event_count,
        },
        next_actions=["confirm_date_window"],
    )


def _default_output_path(output_root: Path, fecha_inicio: str, fecha_fin: str) -> Path:
    return output_root / f"agrupamiento-circuitos__{fecha_inicio}__{fecha_fin}.html"


def render_clustering(
    request: ClusteringRequest,
    *,
    data_path: str | Path | None = None,
    output_root: str | Path | None = None,
) -> ClusteringOutcome:
    try:
        frame, fecha_inicio, fecha_fin, event_count = _resolve_window(request, data_path=data_path)
        fig = plot_interactive_circuit_clustering(
            frame,
            start_date=fecha_inicio,
            end_date=fecha_fin,
            highlighted_circuits=None,
        )
        target_root = Path(output_root) if output_root is not None else DEFAULT_OUTPUT_ROOT
        target = _default_output_path(target_root, fecha_inicio, fecha_fin)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            fig.to_html(
                full_html=True,
                include_plotlyjs=True,
                div_id="circuit-clustering-chart",
            ),
            encoding="utf-8",
        )
    except (FileNotFoundError, ValueError, ReportPipelineError) as exc:
        return ClusteringOutcome(status="execution_error", request=request, errors=[str(exc)])
    return ClusteringOutcome(
        status="success",
        request=request,
        resolved_window={
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "event_count": event_count,
        },
        output_html=str(target),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m chec_local_interpreter.circuit_clustering_contract"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_request_args(command: argparse.ArgumentParser) -> None:
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

    render_command = subparsers.add_parser("render")
    add_request_args(render_command)
    render_command.add_argument("--data-path")
    render_command.add_argument("--output-root")

    return parser


def _request_from_args(args: argparse.Namespace) -> ClusteringRequest:
    return normalize_request(
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
            ClusteringOutcome(
                status="awaiting_confirmation",
                request=request,
                next_actions=["confirm_date_window"],
            ).to_json_text()
        )
        return 0
    if args.command == "preflight":
        outcome = preflight_clustering(request, data_path=args.data_path)
        print(outcome.to_json_text())
        return 0 if outcome.status == "awaiting_confirmation" else 2
    if args.command == "render":
        outcome = render_clustering(
            request,
            data_path=args.data_path,
            output_root=args.output_root,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status == "success" else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
