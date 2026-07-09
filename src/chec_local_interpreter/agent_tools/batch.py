"""L4 headless batch orchestration for the expert-alignment pilot agent.

Runs one isolated headless agent invocation per circuit, gates every
response through the L2 `validate` verb (schema + provenance, WU1/WU2), and
never publishes invalid output. This module reuses the L1/L2 building
blocks (`build_context`, `validate`, `sanitize_circuito_dirname`,
`TOOL_VERSION`) from `chec_local_interpreter.agent_tools.expert_alignment`
in-process — it does not duplicate their logic.

Per design's Failure handling section:
    - Each circuit run is isolated; result = exit code + validated/not.
    - Validation fail -> retry up to `MAX_VALIDATION_RETRIES` with the
      validator's errors fed back into the prompt (repair pattern).
    - Still failing -> the L2 `validate` verb has already written the raw
      output + errors under `reports/interpretability/artifacts/{circuito}/`;
      the circuit is marked FAILED in the run manifest and the batch
      continues to the next circuit (it never aborts).
    - Invalid output is NEVER written to the published report path.
    - The run manifest records per-circuit status, artifact paths,
      tool_version, timestamp, and retry counts.
    - A hard subprocess failure (non-zero return code: auth error, crash,
      etc.) is recorded distinctly as `AGENT_ERROR` with the captured
      stderr, instead of consuming the retry budget as a generic validation
      failure.
    - A duplicate `circuito` within the same batch is never re-run (which
      would silently overwrite the first run's published report); the
      second and later occurrences are recorded as `SKIPPED_DUPLICATE`.
    - Any other unexpected error while building context, invoking the
      agent, or writing artifacts is also captured as a `FAILED` manifest
      entry — one circuit's failure never aborts the batch, by construction.

The agent command is injectable (`command=` on `run_circuit`/`run_batch`,
or `--agent-command` on the CLI) so the real L3 agent-role wiring (WU5) can
override it; if the configured command is not on PATH, the circuit is
marked FAILED with a clear error in the manifest instead of a traceback. A
hung agent invocation is bounded by `timeout=`/`--timeout`
(`DEFAULT_AGENT_TIMEOUT_SECONDS` by default) so it can never block the
batch indefinitely.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from chec_local_interpreter.agent_tools.expert_alignment import (
    TOOL_VERSION,
    build_context,
    sanitize_circuito_dirname,
    validate,
)

MAX_VALIDATION_RETRIES = 2

# A hung `claude -p` must never block the batch indefinitely. This default is
# threaded through run_circuit -> run_batch -> the CLI's --timeout flag, all
# the way down to the sole `subprocess.run` boundary in `_invoke_agent`.
DEFAULT_AGENT_TIMEOUT_SECONDS = 120.0

# The L3 agent role file (`.claude/agents/expert-alignment.md`) arrives in
# WU5; until then this is a thin, injectable command template so the real
# wiring can be swapped in without changing this module's control flow.
DEFAULT_AGENT_COMMAND: tuple[str, ...] = ("claude", "-p")

# Relative to the invocation cwd, same convention as
# `agent_tools.expert_alignment.ARTIFACTS_ROOT` — callers are expected to
# run this CLI from the repo root.
PUBLISHED_REPORTS_ROOT = Path("reports/interpretability/published")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _invoke_agent(
    prompt: str,
    *,
    command: Sequence[str] = DEFAULT_AGENT_COMMAND,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """Run one isolated headless agent invocation for a single prompt.

    The command template is injectable; callers control exactly how the
    agent is invoked. Raises `FileNotFoundError` / `subprocess.TimeoutExpired`
    on infrastructure failures — callers (here, `run_circuit`) are
    responsible for turning those into a clean manifest entry rather than a
    crash.
    """
    return subprocess.run([*command, prompt], capture_output=True, text=True, timeout=timeout)


def _build_retry_prompt(previous_prompt: str, errors: list[str]) -> str:
    errors_block = "\n".join(f"- {error}" for error in errors) or "- (no specific errors reported)"
    return (
        f"{previous_prompt}\n\n"
        "## Errores de validación de tu respuesta anterior (corrige y reintenta)\n"
        f"{errors_block}\n"
    )


def _atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically.

    Writes to a temp file in the same directory first, then `os.replace()`s
    it into place. `os.replace()` is atomic on the same filesystem, so a
    crash/exception mid-write can never leave `path` truncated or corrupt —
    either the previous content (if any) survives untouched, or the new
    content lands whole. The temp file is cleaned up if anything raises
    before the replace completes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _publish_report(circuito: str, data: dict[str, Any]) -> Path:
    safe_name = sanitize_circuito_dirname(circuito)
    PUBLISHED_REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = PUBLISHED_REPORTS_ROOT / f"{safe_name}.json"
    _atomic_write_text(report_path, json.dumps(data, ensure_ascii=False, indent=2))
    return report_path


def _manifest_entry(
    *,
    circuito: str,
    status: str,
    artifact_paths: list[str],
    retries: int,
    error: str | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "circuito": circuito,
        "status": status,
        "artifact_paths": artifact_paths,
        "tool_version": TOOL_VERSION,
        "timestamp": _utc_timestamp(),
        "retries": retries,
    }
    if error is not None:
        entry["error"] = error
    if errors:
        entry["errors"] = errors
    return entry


def run_circuit(
    payload: dict[str, Any],
    *,
    max_retries: int = MAX_VALIDATION_RETRIES,
    command: Sequence[str] = DEFAULT_AGENT_COMMAND,
    timeout: float | None = DEFAULT_AGENT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one circuit end to end: build-context -> invoke agent -> validate -> retry -> publish/fail.

    Never raises, for either expected failure modes (schema/provenance
    validation failure, missing agent executable, invocation timeout) or any
    other unexpected error while building context, invoking the agent, or
    writing artifacts (e.g. an unsanitizable `circuito` value or a malformed
    `periodo_inicio`/`periodo_fin`) — always returns a manifest entry dict, so
    the caller (`run_batch`) can continue to the next circuit unconditionally.
    This is the module's own documented invariant: one circuit's failure
    never aborts the batch.
    """
    circuito = str(payload.get("circuito") or "unknown")
    artifact_paths: list[str] = []
    attempt = 0

    try:
        envelope = build_context(payload)
        prompt = envelope["prompt"]

        while True:
            try:
                process = _invoke_agent(prompt, command=command, timeout=timeout)
            except FileNotFoundError:
                return _manifest_entry(
                    circuito=circuito,
                    status="FAILED",
                    artifact_paths=artifact_paths,
                    retries=attempt,
                    error=f"agent command not found on PATH: {' '.join(command)}",
                )
            except subprocess.TimeoutExpired as exc:
                return _manifest_entry(
                    circuito=circuito,
                    status="FAILED",
                    artifact_paths=artifact_paths,
                    retries=attempt,
                    error=f"agent invocation timed out: {exc}",
                )

            if process.returncode != 0:
                # A hard subprocess failure (auth error, crash, non-zero exit)
                # is a distinct infrastructure failure, not a normal
                # validation failure — do not consume the retry budget on it,
                # and surface the real stderr instead of a generic message.
                return _manifest_entry(
                    circuito=circuito,
                    status="AGENT_ERROR",
                    artifact_paths=artifact_paths,
                    retries=attempt,
                    error=(
                        f"agent process exited with a non-zero return code "
                        f"({process.returncode}): {process.stderr}"
                    ),
                )

            result, _exit_code = validate({"response_text": process.stdout, "context": envelope["context"]})

            if result.get("ok"):
                report_path = _publish_report(circuito, result["data"])
                return _manifest_entry(
                    circuito=circuito,
                    status="ok",
                    artifact_paths=[str(report_path)],
                    retries=attempt,
                )

            # validate() already wrote the failure artifact (schema or provenance
            # errors, combined) under reports/interpretability/artifacts/{circuito}/.
            if "artifact_path" in result:
                artifact_paths.append(result["artifact_path"])

            if attempt >= max_retries:
                return _manifest_entry(
                    circuito=circuito,
                    status="FAILED",
                    artifact_paths=artifact_paths,
                    retries=attempt,
                    error="validation failed after exhausting retries",
                    errors=result.get("errors", []),
                )

            prompt = _build_retry_prompt(prompt, result.get("errors", []))
            attempt += 1
    except Exception as exc:  # noqa: BLE001 - one circuit's failure must never abort the batch
        return _manifest_entry(
            circuito=circuito,
            status="FAILED",
            artifact_paths=artifact_paths,
            retries=attempt,
            error=f"unexpected error while processing circuit: {exc}",
        )


def run_batch(
    payloads: list[dict[str, Any]],
    *,
    max_retries: int = MAX_VALIDATION_RETRIES,
    command: Sequence[str] = DEFAULT_AGENT_COMMAND,
    timeout: float | None = DEFAULT_AGENT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run every circuit in `payloads`; a failing circuit never aborts the batch.

    Duplicate `circuito` values within the same batch are detected: the
    second and later occurrences are marked `SKIPPED_DUPLICATE` instead of
    being re-run, which would otherwise silently overwrite the first run's
    published report with no signal in the manifest.
    """
    seen_circuitos: set[str] = set()
    circuits: list[dict[str, Any]] = []
    for payload in payloads:
        circuito = str(payload.get("circuito") or "unknown")
        if circuito in seen_circuitos:
            circuits.append(
                _manifest_entry(
                    circuito=circuito,
                    status="SKIPPED_DUPLICATE",
                    artifact_paths=[],
                    retries=0,
                    error=(
                        f"duplicate circuito '{circuito}' in this batch; skipped to avoid "
                        "silently overwriting the first run's published report"
                    ),
                )
            )
            continue
        seen_circuitos.add(circuito)
        circuits.append(run_circuit(payload, max_retries=max_retries, command=command, timeout=timeout))
    return {
        "tool_version": TOOL_VERSION,
        "generated_at": _utc_timestamp(),
        "circuits": circuits,
    }


def _load_circuit_payloads(paths: list[str]) -> list[dict[str, Any]]:
    """Load per-circuit context-build payloads from `--circuits` arguments.

    Each argument is a path to a JSON file containing either a single
    circuit payload (an object with a "circuito" key, among others) or a
    list of such payload objects (a circuits manifest). Multiple `--circuits`
    arguments are concatenated in order — this is the "list-or-file" CLI
    contract: pass one manifest file, or several per-circuit files.
    """
    payloads: list[dict[str, Any]] = []
    for path_str in paths:
        path = Path(path_str)
        data = json.loads(path.read_text())
        if isinstance(data, list):
            payloads.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            payloads.append(data)
        else:
            raise ValueError(f"{path}: must contain a JSON object or a list of JSON objects")
    return payloads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.agent_tools.batch")
    parser.add_argument(
        "--circuits",
        nargs="+",
        required=True,
        help=(
            "One or more paths to JSON files. Each file contains either a single "
            "circuit context-build payload (object) or a list of them."
        ),
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=MAX_VALIDATION_RETRIES,
        help=f"Validation retry limit per circuit (default: {MAX_VALIDATION_RETRIES}).",
    )
    parser.add_argument(
        "--manifest-out",
        default=None,
        help="Optional path to also write the run manifest to a file (in addition to stdout).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_AGENT_TIMEOUT_SECONDS,
        help=(
            "Per-invocation timeout in seconds for the agent subprocess "
            f"(default: {DEFAULT_AGENT_TIMEOUT_SECONDS})."
        ),
    )
    args = parser.parse_args(argv)

    payloads = _load_circuit_payloads(args.circuits)
    manifest = run_batch(payloads, max_retries=args.max_retries, timeout=args.timeout)

    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if args.manifest_out:
        Path(args.manifest_out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    any_failed = any(entry["status"] != "ok" for entry in manifest["circuits"])
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
