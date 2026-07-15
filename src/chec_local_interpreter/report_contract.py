"""Shared report invocation contract for runtime-native report adapters.

This module normalizes runtime-specific invocations into a small, JSON-serializable
contract. Report-domain behavior remains owned by :mod:`chec_local_interpreter.report_pipeline`;
adapters should use this boundary instead of duplicating pipeline rules.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Sequence

from chec_local_interpreter.agent_output import ReportPipelineError
from chec_local_interpreter import report_pipeline

SCHEMA_VERSION = "report-contract/v1"
UNKNOWN_MODEL_LABEL = "Desconocido"

ReportStatus = Literal[
    "awaiting_confirmation",
    "ready_for_roles",
    "ready_for_alignment",
    "success",
    "usage_error",
    "execution_error",
]


@dataclass(frozen=True)
class RuntimeMetadata:
    """Runtime/provider/model identity supplied by the invoking adapter."""

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
class ReportRequest:
    """Normalized report request used by every runtime adapter."""

    circuito: str
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    runtime: RuntimeMetadata = field(default_factory=RuntimeMetadata)

    def to_json(self) -> dict[str, Any]:
        return {
            "circuito": self.circuito,
            "fecha_inicio": self.fecha_inicio,
            "fecha_fin": self.fecha_fin,
            "runtime": self.runtime.to_json(),
        }


@dataclass(frozen=True)
class ReportOutcome:
    """Machine-readable lifecycle outcome emitted by the shared contract."""

    status: ReportStatus
    request: ReportRequest | None = None
    run_dir: str | None = None
    report_html: str | None = None
    resolved_window: dict[str, Any] | None = None
    next_actions: list[str] = field(default_factory=list)
    degradations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "request": self.request.to_json() if self.request else None,
            "run_dir": self.run_dir,
            "report_html": self.report_html if self.status == "success" else None,
            "resolved_window": self.resolved_window,
            "next_actions": list(self.next_actions),
            "degradations": list(self.degradations),
            "errors": list(self.errors),
        }
        return data

    def to_json_text(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)


def normalize_request(
    circuito: str | None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    *,
    runtime: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> ReportRequest:
    """Validate adapter syntax and produce a canonical request.

    This deliberately performs syntax-level validation only. Dataset authority,
    circuit existence, date-window eligibility, and report generation remain in
    ``report_pipeline``.
    """

    normalized_circuito = (circuito or "").strip()
    if not normalized_circuito:
        raise ValueError("circuito is required")
    if (fecha_inicio is None) != (fecha_fin is None):
        raise ValueError(
            "fecha_inicio and fecha_fin must be provided together or both omitted"
        )
    return ReportRequest(
        circuito=normalized_circuito,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        runtime=RuntimeMetadata(runtime=runtime, provider=provider, model=model),
    )


def usage_error(message: str, request: ReportRequest | None = None) -> ReportOutcome:
    return ReportOutcome(status="usage_error", request=request, errors=[message])


def awaiting_confirmation(request: ReportRequest) -> ReportOutcome:
    return ReportOutcome(
        status="awaiting_confirmation",
        request=request,
        next_actions=["confirm_circuit_and_date_window"],
    )


def preflight_report(
    request: ReportRequest, *, data_path: str | Path | None = None
) -> ReportOutcome:
    """Resolve the report window through the canonical pipeline preflight hook."""

    try:
        resolved = report_pipeline.preflight(
            request.circuito,
            request.fecha_inicio,
            request.fecha_fin,
            data_path=data_path,
        )
    except ReportPipelineError as exc:
        return ReportOutcome(status="execution_error", request=request, errors=[str(exc)])
    return ReportOutcome(
        status="awaiting_confirmation",
        request=request,
        resolved_window={
            "circuito": resolved.circuito,
            "fecha_inicio": resolved.fecha_inicio,
            "fecha_fin": resolved.fecha_fin,
            "event_count": resolved.event_count,
        },
        next_actions=["confirm_circuit_and_date_window"],
    )


def prepare_report(request: ReportRequest, *, data_path: str | Path | None = None, runs_root: str | Path | None = None) -> ReportOutcome:
    """Run the canonical prepare stage and return a JSON-safe outcome."""

    try:
        run_dir = report_pipeline.prepare(
            request.circuito,
            request.fecha_inicio,
            request.fecha_fin,
            data_path=data_path,
            runs_root=runs_root,
        )
    except ReportPipelineError as exc:
        return ReportOutcome(status="execution_error", request=request, errors=[str(exc)])
    return ReportOutcome(
        status="ready_for_roles",
        request=request,
        run_dir=str(run_dir),
        next_actions=["run_historical_inference_and_auto_simulator_roles"],
    )


def prepare_alignment(request: ReportRequest, run_dir: str | Path, *, pdf_discussions_path: str | Path | None = None) -> ReportOutcome:
    """Run the canonical expert-alignment preparation stage."""

    try:
        alignment_context = report_pipeline.prepare_expert_alignment(
            run_dir, pdf_discussions_path=pdf_discussions_path
        )
    except ReportPipelineError as exc:
        return ReportOutcome(
            status="execution_error", request=request, run_dir=str(run_dir), errors=[str(exc)]
        )
    return ReportOutcome(
        status="ready_for_alignment",
        request=request,
        run_dir=str(Path(alignment_context).parent),
        next_actions=["run_expert_alignment_role"],
    )


def _pi_session_dir_for_cwd(cwd: Path) -> Path:
    """Return Pi's session-history directory for ``cwd``.

    Pi currently stores per-directory histories under a filename-safe form that
    wraps the slash-separated absolute path with ``--`` and joins path parts with
    ``-`` (for example ``/Users/me/project`` becomes ``--Users-me-project--``).
    """

    encoded_cwd = "--" + "-".join(cwd.resolve().parts[1:]) + "--"
    return Path.home() / ".pi" / "agent" / "sessions" / encoded_cwd


def _model_from_pi_session_history(cwd: Path | None = None) -> tuple[str, str] | None:
    """Return the latest effective Pi model as ``(provider, model)``.

    Session history is execution evidence: it records explicit ``model_change``
    events and assistant messages with the provider/model that actually ran.
    Static adapter frontmatter is intentionally not consulted.
    """

    session_dir = _pi_session_dir_for_cwd(cwd or Path.cwd())
    if not session_dir.exists():
        return None

    session_files = sorted(session_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime)
    for session_file in reversed(session_files):
        latest: tuple[str, str] | None = None
        try:
            lines = session_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "model_change":
                provider = str(entry.get("provider") or "").strip()
                model = str(entry.get("modelId") or "").strip()
                if provider and model:
                    latest = (provider, model)
            elif entry.get("type") == "message":
                message = entry.get("message") or {}
                if message.get("role") == "assistant":
                    provider = str(message.get("provider") or "").strip()
                    model = str(message.get("model") or "").strip()
                    if provider and model:
                        latest = (provider, model)
        if latest:
            return latest
    return None


def _model_from_pi_settings() -> tuple[str, str] | None:
    settings_path = Path.home() / ".pi" / "agent" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    provider = str(settings.get("defaultProvider") or "").strip()
    model = str(settings.get("defaultModel") or "").strip()
    if provider and model:
        return provider, model
    return None


def _is_pi_runtime(runtime: str | None) -> bool:
    normalized_runtime = (runtime or "").strip().lower()
    if normalized_runtime:
        return normalized_runtime == "pi"
    return os.environ.get("PI_CODING_AGENT") == "true"


def _resolve_effective_runtime_metadata(
    metadata: RuntimeMetadata,
    *,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> RuntimeMetadata:
    """Resolve the report-authoring provider/model from real runtime evidence.

    Priority: explicit render arguments, normalized request metadata, CHEC env
    overrides, then runtime-specific active/configured model. Markdown
    frontmatter is not a reliable execution source and is deliberately ignored.
    """

    provider = (llm_provider or metadata.provider or os.environ.get("CHEC_LLM_PROVIDER") or "").strip() or None
    model = (llm_model or metadata.model or os.environ.get("CHEC_LLM_MODEL") or "").strip() or None
    runtime = metadata.runtime

    if _is_pi_runtime(runtime):
        provider = provider or "el-gentleman"
        if model is None:
            pi_model = _model_from_pi_session_history() or _model_from_pi_settings()
            if pi_model:
                pi_provider, pi_model_id = pi_model
                model = f"{pi_provider}/{pi_model_id}"

    return RuntimeMetadata(runtime=runtime, provider=provider, model=model)


def render_report(
    request: ReportRequest,
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> ReportOutcome:
    """Run canonical rendering and expose the terminal report path on success."""

    resolved_runtime = _resolve_effective_runtime_metadata(
        request.runtime,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    resolved_request = replace(request, runtime=resolved_runtime)

    try:
        report_html = report_pipeline.render(
            run_dir,
            output_dir=output_dir,
            llm_provider=resolved_runtime.provider,
            llm_model=resolved_runtime.model,
        )
    except ReportPipelineError as exc:
        return ReportOutcome(
            status="execution_error", request=resolved_request, run_dir=str(run_dir), errors=[str(exc)]
        )
    return ReportOutcome(
        status="success",
        request=resolved_request,
        run_dir=str(run_dir),
        report_html=str(report_html),
    )


def render_report_strict(request: ReportRequest, run_dir: str | Path, *, expected_roles: Sequence[str], executed_roles: Sequence[str], output_dir: str | Path | None = None) -> ReportOutcome:
    verification = report_pipeline.verify_token_usage(run_dir, expected_roles=expected_roles, executed_roles=executed_roles)
    if not verification.ok:
        return ReportOutcome(status="execution_error", request=request, run_dir=str(run_dir), errors=["token usage verification failed"] + list(verification.errors) + list(verification.missing_measurements) + list(verification.invalid_roles))
    return render_report(request, run_dir, output_dir=output_dir)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.report_contract")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_request_args(command: argparse.ArgumentParser) -> None:
        command.add_argument("circuito")
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

    prepare_command = subparsers.add_parser("prepare")
    add_request_args(prepare_command)
    prepare_command.add_argument("--data-path")
    prepare_command.add_argument("--runs-root")

    alignment_command = subparsers.add_parser("prepare-alignment")
    add_request_args(alignment_command)
    alignment_command.add_argument("--run-dir", required=True)
    alignment_command.add_argument("--pdf-discussions-path")

    render_command = subparsers.add_parser("render")
    add_request_args(render_command)
    render_command.add_argument("--run-dir", required=True)
    render_command.add_argument("--output-dir")
    render_command.add_argument("--require-measured-usage", action="store_true")
    render_command.add_argument("--expected-role", action="append", default=[])
    render_command.add_argument("--executed-role", action="append", default=[])

    record_command = subparsers.add_parser("record-usage")
    record_command.add_argument("--run-dir", required=True)
    record_command.add_argument("--stage", required=True)
    usage_shape = record_command.add_mutually_exclusive_group(required=True)
    usage_shape.add_argument("--total", type=int)
    usage_shape.add_argument("--input", type=int)
    record_command.add_argument("--output", type=int)
    verify_command = subparsers.add_parser("verify-usage")
    verify_command.add_argument("--run-dir", required=True)
    verify_command.add_argument("--expected-role", action="append", default=[])
    verify_command.add_argument("--executed-role", action="append", default=[])
    return parser


def _request_from_args(args: argparse.Namespace) -> ReportRequest:
    return normalize_request(
        args.circuito,
        args.fecha_inicio,
        args.fecha_fin,
        runtime=args.runtime,
        provider=args.provider,
        model=args.model,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "record-usage":
        try:
            if args.total is not None:
                usage = report_pipeline.record_token_usage(args.run_dir, args.stage, total=args.total)
            else:
                usage = report_pipeline.record_token_usage(args.run_dir, args.stage, input=args.input, output=args.output)
        except (ValueError, ReportPipelineError) as exc:
            print(json.dumps({"status": "error", "errors": [str(exc)]}, sort_keys=True))
            return 2
        print(json.dumps({"status": "success", "usage": usage}, sort_keys=True))
        return 0
    if args.command == "verify-usage":
        result = report_pipeline.verify_token_usage(args.run_dir, expected_roles=args.expected_role, executed_roles=args.executed_role)
        print(json.dumps(result.to_json(), sort_keys=True))
        return 0 if result.ok else 2
    try:
        request = _request_from_args(args)
    except ValueError as exc:
        print(usage_error(str(exc)).to_json_text())
        return 2

    if args.command == "parse":
        print(ReportOutcome(status="awaiting_confirmation", request=request).to_json_text())
        return 0
    if args.command == "preflight":
        print(preflight_report(request, data_path=args.data_path).to_json_text())
        return 0
    if args.command == "prepare":
        print(prepare_report(request, data_path=args.data_path, runs_root=args.runs_root).to_json_text())
        return 0
    if args.command == "prepare-alignment":
        print(
            prepare_alignment(
                request, args.run_dir, pdf_discussions_path=args.pdf_discussions_path
            ).to_json_text()
        )
        return 0
    if args.command == "render":
        if args.require_measured_usage and not args.executed_role:
            print(json.dumps({"status": "error", "errors": ["--require-measured-usage requires at least one --executed-role"]}, sort_keys=True))
            return 2
        if args.require_measured_usage:
            outcome = render_report_strict(
                request,
                args.run_dir,
                expected_roles=args.expected_role,
                executed_roles=args.executed_role,
                output_dir=args.output_dir,
            )
        else:
            outcome = render_report(
                request,
                args.run_dir,
                output_dir=args.output_dir,
                llm_provider=request.runtime.provider,
                llm_model=request.runtime.model,
            )
        print(outcome.to_json_text())
        return 0 if outcome.status == "success" else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
