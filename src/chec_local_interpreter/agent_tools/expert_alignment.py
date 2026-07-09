"""L2 tool-adapter CLI for the expert-alignment pilot agent.

This module is a thin stdin/stdout JSON boundary around the deterministic,
already-validated functions in `chec_local_interpreter.expert_alignment`
(L1). It has no import path to the model training package or the frozen
classifier artifact: it packages precomputed context and gates output
through the existing validator, it does not implement any new selection
logic.

Verbs:
    build-context   Reads circuit/context inputs from stdin JSON, emits the
                    envelope `{meta, context, prompt, allowed}` on stdout.
    validate        Reads `{response_text, context}` from stdin JSON, runs
                    the existing validator, and on failure writes the raw
                    output plus errors under
                    `reports/interpretability/artifacts/{circuito}/`.

Both verbs read exactly one JSON document from stdin and write exactly one
JSON document to stdout. No network access, no imports outside
`chec_local_interpreter.expert_alignment`, the sibling `agent_tools._atomic_io`
shared-utility module (the hoisted atomic-write helper, shared with
`agent_tools.batch` so it only needs to exist in one place), and the standard
library.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text as _atomic_write_text
from chec_local_interpreter.expert_alignment import (
    allowed_dates,
    allowed_pdf_row_indexes,
    allowed_variables,
    compactar_contexto_expert_alignment_para_prompt,
    construir_contexto_expert_alignment,
    construir_prompt_expert_alignment,
    validar_provenance_expert_alignment,
    validar_respuesta_expert_alignment,
)

TOOL_VERSION = "expert-alignment-agent-tools/0.1.0"

# Relative to the invocation cwd. Callers (e.g. the headless batch runner) are
# expected to run this CLI from the repo root so failure artifacts land under
# the repo's own reports/interpretability/artifacts/ directory.
ARTIFACTS_ROOT = Path("reports/interpretability/artifacts")


class MalformedRequestError(Exception):
    """Raised when the stdin payload is not valid JSON or misses a required field."""


def build_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the `build-context` envelope from a raw stdin JSON payload."""
    context = construir_contexto_expert_alignment(
        circuito=payload["circuito"],
        periodo_inicio=payload.get("periodo_inicio"),
        periodo_fin=payload.get("periodo_fin"),
        fechas_informe=payload.get("fechas_informe", []),
        validation_data=payload.get("validation_data", {}),
        inference_validation_data=payload.get("inference_validation_data", {}),
        pdf_expert_matches=payload.get("pdf_expert_matches", []),
        inference_context_package=payload.get("inference_context_package"),
        variables_modelo_predictivo=payload.get("variables_modelo_predictivo"),
    )
    compact_context = compactar_contexto_expert_alignment_para_prompt(context)
    prompt = construir_prompt_expert_alignment(context, payload.get("skill_bundle", ""))

    return {
        "meta": {
            "circuito": context["circuito"],
            "periodo": context["periodo_informe"],
            "tool_version": TOOL_VERSION,
        },
        "context": compact_context,
        "prompt": prompt,
        # `allowed` must be derived from `compact_context` — the SAME object
        # used for the prompt and passed to `validate()` — not the full,
        # untruncated `context`. `fechas_informe` (top 20) and
        # `pdf_expert_matches` (top 10) are truncated in `compact_context`;
        # advertising an "allowed" date/index that fell outside that
        # truncation would let a genuinely correct agent response exhaust
        # retries and fail purely from this internal inconsistency.
        "allowed": {
            "dates": sorted(allowed_dates(compact_context)),
            "variables": sorted(allowed_variables(compact_context)),
            "pdf_row_indexes": sorted(allowed_pdf_row_indexes(compact_context)),
            "sources": list(compact_context.get("fuentes_disponibles", [])),
        },
    }


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_CIRCUITO_DIRNAME_LENGTH = 128


def _sanitize_circuito_dirname(circuito: str) -> str:
    """Reduce an untrusted `circuito` value to a single, safe directory name.

    Strips ASCII control characters first (including an embedded NUL byte,
    which would otherwise crash `Path.resolve()`/`mkdir()`/`write_text()`
    with `ValueError: embedded null byte`). Then `Path(...).name` strips any
    directory separators and `..`/absolute-path components, so a value like
    "../../../../etc/evil" collapses to "evil" and can never be used to
    escape `ARTIFACTS_ROOT`. Falls back to "unknown" for any input that
    collapses to nothing usable, and caps the result length so an
    oversized `circuito` can never trip a filesystem name-length limit.
    """
    cleaned = _CONTROL_CHARS_RE.sub("", str(circuito or "")).strip()
    name = Path(cleaned).name
    if not name or name in {".", ".."}:
        return "unknown"
    return name[:_MAX_CIRCUITO_DIRNAME_LENGTH]


def sanitize_circuito_dirname(circuito: str) -> str:
    """Public re-export of `_sanitize_circuito_dirname` for reuse by the batch runner (WU4)."""
    return _sanitize_circuito_dirname(circuito)


def _write_failure_artifact(circuito: str, response_text: str, errors: list[str]) -> Path:
    artifacts_root = ARTIFACTS_ROOT.resolve()
    safe_name = _sanitize_circuito_dirname(circuito)
    artifact_dir = (ARTIFACTS_ROOT / safe_name).resolve()
    # Defense in depth: sanitization above should already guarantee containment,
    # but never mkdir/write outside ARTIFACTS_ROOT even if that guarantee is
    # ever weakened by a future change.
    if artifact_dir != artifacts_root and artifacts_root not in artifact_dir.parents:
        artifact_dir = artifacts_root / "unknown"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"invalid_{time.time_ns()}.json"
    _atomic_write_text(
        artifact_path,
        json.dumps({"response_text": response_text, "errors": errors}, ensure_ascii=False, indent=2),
    )
    return artifact_path


def validate(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Run the `validate` verb: gate a candidate response through the L1 validators.

    Runs the schema validator first, then — only if it succeeds — the
    additive provenance validator (`validar_provenance_expert_alignment`),
    combining both error lists. Exit code 0 requires both to pass; a response
    without any `provenance` keys at all is unaffected (backwards compatible)
    since the provenance validator has nothing to check.

    Returns `(result, exit_code)`. On failure, writes the raw response and
    combined errors under `reports/interpretability/artifacts/{circuito}/`
    and never returns `ok: true`.
    """
    response_text = payload["response_text"]
    context = payload.get("context", {})
    result = validar_respuesta_expert_alignment(response_text, context)
    errors = list(result["errors"])
    ok = result["ok"]

    if ok:
        provenance_result = validar_provenance_expert_alignment(result["data"], context)
        errors.extend(provenance_result["errors"])
        ok = provenance_result["ok"]

    if ok:
        return {"ok": True, "data": result["data"]}, 0

    circuito = str(context.get("circuito") or "unknown")
    artifact_path = _write_failure_artifact(circuito, response_text, errors)
    return {"ok": False, "errors": errors, "artifact_path": str(artifact_path)}, 1


def _load_payload(verb: str) -> dict[str, Any]:
    """Parse stdin as a JSON object and check the verb's required top-level keys.

    Raises `MalformedRequestError` for empty/invalid JSON, a non-object
    payload, or a missing required field — kept distinct from a validation
    failure (exit code 1), which requires a well-formed request in the first
    place.
    """
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise MalformedRequestError(f"stdin is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise MalformedRequestError("stdin JSON payload must be an object.")

    required_key = "circuito" if verb == "build-context" else "response_text"
    if required_key not in payload:
        raise MalformedRequestError(f"Missing required field: {required_key}")

    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.agent_tools.expert_alignment")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    subparsers.add_parser("build-context", help="Emit the context+prompt+allowed envelope for a circuit.")
    subparsers.add_parser("validate", help="Validate a candidate expert-alignment response against its context.")
    args = parser.parse_args(argv)

    try:
        payload = _load_payload(args.verb)
    except MalformedRequestError as exc:
        json.dump({"ok": False, "errors": [f"Malformed request: {exc}"]}, sys.stdout, ensure_ascii=False)
        return 2

    try:
        if args.verb == "build-context":
            envelope = build_context(payload)
            json.dump(envelope, sys.stdout, ensure_ascii=False)
            return 0

        result, exit_code = validate(payload)
        json.dump(result, sys.stdout, ensure_ascii=False)
        return exit_code
    except Exception as exc:  # noqa: BLE001 - a well-formed request with malformed
        # nested fields must still produce exactly one JSON document on
        # stdout, never a bare traceback / no output at all. The full
        # traceback still goes to stderr for diagnosability (same convention
        # as `batch.run_circuit`'s unexpected-error handling).
        print(f"[chec_local_interpreter.agent_tools.expert_alignment] unexpected error:\n{traceback.format_exc()}", file=sys.stderr)
        json.dump({"ok": False, "errors": [f"Unexpected error: {exc}"]}, sys.stdout, ensure_ascii=False)
        return 3


if __name__ == "__main__":
    sys.exit(main())
