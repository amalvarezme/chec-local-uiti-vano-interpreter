"""L2 tool-adapter CLI for the historical/base descriptive agent.

This module is a thin stdin/stdout JSON boundary around the deterministic,
already-validated functions in `chec_local_interpreter.context_builder`,
`chec_local_interpreter.llm_contracts`, and `chec_local_interpreter.llm_validation`
(L1). It has no import path to the model training package or the frozen
classifier artifact: it packages an already-built context and gates output
through the existing schema/guardrail validator plus the additive provenance
validator, it does not implement any new selection logic.

Verbs:
    build-context   Reads the already-built `context_builder.build_context_package(...)`
                    JSON output from stdin, emits the envelope
                    `{meta, context, allowed}` on stdout. Deterministic
                    selection stays entirely upstream of this CLI (Rule 2):
                    the stdin payload IS the deterministic context, never
                    DataFrames or raw selection inputs. The importable
                    `build_context()` function itself still returns `prompt`
                    too, for `agent_tools/batch.py`'s direct in-process use.
    validate        Reads `{response_text, context}` from stdin JSON, runs the
                    existing schema/guardrail validator first and — only if
                    that passes — the additive provenance validator
                    (`validar_provenance_base`), combining both error lists.
                    On failure, writes the raw output plus errors under
                    `reports/interpretability/artifacts/historical/{circuito}/`.

Both verbs read exactly one JSON document from stdin and write exactly one
JSON document to stdout, via the shared `agent_tools.cli_support.dispatch`
0/1/2/3 exit-code contract. No network access, no imports outside
`chec_local_interpreter.llm_contracts`, `chec_local_interpreter.llm_validation`,
`chec_local_interpreter.circuit_identity` (the shared, agent-agnostic
canonical-identity module), the sibling `agent_tools._atomic_io` and
`agent_tools.cli_support` shared-utility modules, and the standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text as _atomic_write_text
from chec_local_interpreter.agent_tools.cli_support import dispatch as cli_dispatch
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.llm_contracts import load_output_schema, render_prompt
from chec_local_interpreter.llm_validation import (
    allowed_critical_point_ids,
    allowed_dates,
    unavailable_columns,
    validar_provenance_base,
    validate_llm_response,
)

TOOL_VERSION = "historical-agent-tools/0.1.0"

# Relative to the invocation cwd, same convention as
# `agent_tools.expert_alignment.ARTIFACTS_ROOT`. Namespaced under its own
# `historical` segment so this agent's failure artifacts can never collide
# with the expert-alignment pilot's (spec: agent-namespaced-reports).
ARTIFACTS_ROOT = Path("reports/interpretability/artifacts/historical")


def _circuito_from_context(context: Any) -> str:
    """Derive the publish/artifact identity from a base context's `metadata.circuitos`.

    Mirrors the existing `"_".join(selected_circuitos)` convention used
    elsewhere in the codebase (the base context is multi-circuit capable).
    Falls back to `"unknown"` for a missing/empty `circuitos` list. Deliberately
    does NOT guard against a non-dict `context`/`metadata` (mirrors
    `agent_tools/expert_alignment.py`'s equivalent `.get()` chain): a
    genuinely malformed context is an unexpected-error case (exit 3 via the
    shared `cli_support` catch-all), not a value this function should
    silently paper over.
    """
    metadata = context.get("metadata") or {}
    circuitos = metadata.get("circuitos") or []
    return "_".join(str(item) for item in circuitos) or "unknown"


def build_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the `build-context` envelope from the already-built context JSON.

    `payload` IS the deterministic `context_builder.build_context_package(...)`
    output (already selected, already JSON-serializable) — this CLI never
    performs its own selection or detection.
    """
    context = payload
    circuito = _circuito_from_context(context)
    schema = load_output_schema()
    prompt = render_prompt(
        context_json=json.dumps(context, ensure_ascii=False),
        output_schema_json=json.dumps(schema, ensure_ascii=False),
    )

    return {
        "meta": {
            "circuito": circuito,
            "tool_version": TOOL_VERSION,
        },
        "context": context,
        "prompt": prompt,
        # Computed via the same public accessors the `validate` verb's
        # schema/guardrail validator uses internally — so the advertised
        # citable universe can never disagree with what `validate` actually
        # enforces.
        "allowed": {
            "dates": sorted(allowed_dates(context)),
            "critical_point_ids": sorted(allowed_critical_point_ids(context)),
            "unavailable_columns": sorted(unavailable_columns(context)),
        },
    }


def _write_failure_artifact(circuito: str, response_text: str, errors: list[str]) -> Path:
    """Write the raw response + validation errors under `ARTIFACTS_ROOT/{identity}/`.

    Uses `canonical_circuit_identity` (sanitize + normalize) — the same
    identity function every other circuit-derived path in this codebase
    uses — so this agent's failure-artifact directory is deterministic and
    collision-safe regardless of how the raw `circuito` value is cased or
    punctuated.
    """
    artifacts_root = ARTIFACTS_ROOT.resolve()
    safe_name = canonical_circuit_identity(circuito)
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
    """Run the `validate` verb: gate a candidate response through the two-stage L1 validators.

    Runs the schema/guardrail validator (`validate_llm_response`, reused
    unmodified) first, then — only if it succeeds — the additive provenance
    validator (`validar_provenance_base`), combining both error lists. Exit
    code 0 requires both to pass; a response without any `provenance` keys at
    all is unaffected (backwards compatible) since the provenance validator
    has nothing to check. If the first stage fails, the second stage never
    runs — its errors would be meaningless against already-invalid data.

    Returns `(result, exit_code)`. On failure, writes the raw response and
    combined errors under
    `reports/interpretability/artifacts/historical/{circuito}/` and never
    returns `ok: true`.
    """
    response_text = payload["response_text"]
    context = payload.get("context", {})

    result = validate_llm_response(response_text, context)
    errors = list(result.errors)
    ok = result.ok

    if ok:
        provenance_result = validar_provenance_base(result.data, context)
        errors.extend(provenance_result["errors"])
        ok = provenance_result["ok"]

    if ok:
        return {"ok": True, "data": result.data}, 0

    circuito = _circuito_from_context(context)
    artifact_path = _write_failure_artifact(circuito, response_text, errors)
    return {"ok": False, "errors": errors, "artifact_path": str(artifact_path)}, 1


def _build_context_handler(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    envelope = build_context(payload)
    # The CLI's stdout is read by the interactive Claude Code sub-agent (role file's own Skill
    # already supplies its instructions); "prompt" re-serializes "context" as text and roughly
    # doubles the bytes it has to ingest for no informational gain. `build_context()` itself still
    # returns "prompt" unchanged for `agent_tools/batch.py`'s direct in-process import, which needs
    # the full rendered string as the sole argument to its headless subprocess agent call.
    return {k: v for k, v in envelope.items() if k != "prompt"}, 0


_HANDLERS: dict[str, tuple[str, Any]] = {
    "build-context": ("metadata", _build_context_handler),
    "validate": ("response_text", validate),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.agent_tools.historical")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    subparsers.add_parser(
        "build-context",
        help=(
            "Emit the context+allowed envelope for a circuit (prompt omitted from stdout; "
            "still available via direct build_context() import)."
        ),
    )
    subparsers.add_parser("validate", help="Validate a candidate historical/base response against its context.")
    args = parser.parse_args(argv)

    return cli_dispatch(
        args.verb,
        _HANDLERS,
        module_name="chec_local_interpreter.agent_tools.historical",
    )


if __name__ == "__main__":
    sys.exit(main())
