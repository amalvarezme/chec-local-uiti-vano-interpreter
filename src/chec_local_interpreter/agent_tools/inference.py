"""L2 tool-adapter CLI for the inference/MGCECDL agent (Slice A, Phase 3).

This module is a thin stdin/stdout JSON boundary around the deterministic,
already-validated functions in `chec_impacto.interpretability.circuit_analysis`
(`construir_prompt_inferencia`, a pure prompt-rendering function — never the
model-training package or the frozen classifier artifact) and
`chec_local_interpreter.inference_validation` (L1). It packages an
already-built context (per Rule 2 — deterministic selection stays entirely
upstream, in the future `report_pipeline.prepare()` orchestrator) and gates
output through the new two-stage schema/guardrail + provenance validator; it
does not implement any new selection logic.

Verbs:
    build-context   Reads the already-built
                    `circuit_analysis.construir_contexto_inferencia(...)` JSON
                    output from stdin (the deterministic inference context —
                    never DataFrames or raw model/selection inputs), emits
                    the envelope `{meta, context, prompt, allowed}` on
                    stdout.
    validate        Reads `{response_text, context}` from stdin JSON, runs
                    `inference_validation.validar_respuesta_inferencia_strict`
                    first and — only if that passes — the additive
                    `validar_provenance_inferencia`, combining both error
                    lists. On failure, writes the raw output plus errors
                    under
                    `reports/interpretability/artifacts/inference/{circuito}/`.

Both verbs read exactly one JSON document from stdin and write exactly one
JSON document to stdout, via the shared `agent_tools.cli_support.dispatch`
0/1/2/3 exit-code contract. No network access, no imports outside
`chec_impacto.interpretability.circuit_analysis` (pure prompt-rendering only),
`chec_local_interpreter.inference_validation`, `chec_local_interpreter.llm_skills`,
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

from chec_impacto.interpretability.circuit_analysis import construir_prompt_inferencia
from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text as _atomic_write_text
from chec_local_interpreter.agent_tools.cli_support import dispatch as cli_dispatch
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.inference_validation import (
    allowed_critical_point_ids,
    allowed_dates,
    allowed_scenario_names,
    allowed_variables,
    validar_provenance_inferencia,
    validar_respuesta_inferencia_strict,
)
from chec_local_interpreter.llm_skills import assemble_skill_bundle

TOOL_VERSION = "inference-agent-tools/0.1.0"

# Namespaced under its own `inference` segment, same convention as
# `agent_tools.historical.ARTIFACTS_ROOT`, so this agent's failure artifacts
# can never collide with historical's or expert-alignment's.
ARTIFACTS_ROOT = Path("reports/interpretability/artifacts/inference")


def _circuito_from_context(context: Any) -> str:
    """Derive the publish/artifact identity from the inference context's own
    `circuito_interes` field (unlike historical's multi-circuit
    `metadata.circuitos` join — the inference context package is always
    single-circuit). Falls back to `"unknown"` for a missing value."""
    circuito = context.get("circuito_interes")
    return str(circuito) if circuito else "unknown"


def build_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the `build-context` envelope from the already-built context JSON.

    `payload` IS the deterministic
    `circuit_analysis.construir_contexto_inferencia(...)` output (already
    selected, already JSON-serializable) — this CLI never calls that
    function itself, nor performs its own selection (Rule 2). It only
    renders the prompt on top of the already-built context, mirroring
    `agent_tools.historical.build_context`'s relationship to
    `context_builder.build_context_package`.
    """
    context = payload
    circuito = _circuito_from_context(context)
    skill_bundle = assemble_skill_bundle(profile="inferencia")
    prompt = construir_prompt_inferencia(context, skill_bundle)

    return {
        "meta": {
            "circuito": circuito,
            "tool_version": TOOL_VERSION,
        },
        "context": context,
        "prompt": prompt,
        # Computed via the same public accessors the `validate` verb's
        # schema/guardrail and provenance validators use internally — so the
        # advertised citable universe can never disagree with what
        # `validate` actually enforces.
        "allowed": {
            "dates": sorted(allowed_dates(context)),
            "critical_point_ids": sorted(allowed_critical_point_ids(context)),
            "variables": sorted(allowed_variables(context)),
            "scenario_names": sorted(allowed_scenario_names(context)),
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

    Runs the schema/guardrail validator
    (`validar_respuesta_inferencia_strict`) first, then — only if it
    succeeds — the additive provenance validator
    (`validar_provenance_inferencia`), combining both error lists. Exit code
    0 requires both to pass; a response without any `provenance` keys at all
    is unaffected (backwards compatible) since the provenance validator has
    nothing to check. If the first stage fails, the second stage never
    runs — its errors would be meaningless against already-invalid data.

    Returns `(result, exit_code)`. On failure, writes the raw response and
    combined errors under
    `reports/interpretability/artifacts/inference/{circuito}/` and never
    returns `ok: true`.
    """
    response_text = payload["response_text"]
    context = payload.get("context", {})

    result = validar_respuesta_inferencia_strict(response_text, context)
    errors = list(result["errors"])
    ok = result["ok"]

    if ok:
        provenance_result = validar_provenance_inferencia(result["data"], context)
        errors.extend(provenance_result["errors"])
        ok = provenance_result["ok"]

    if ok:
        return {"ok": True, "data": result["data"]}, 0

    circuito = _circuito_from_context(context)
    artifact_path = _write_failure_artifact(circuito, response_text, errors)
    return {"ok": False, "errors": errors, "artifact_path": str(artifact_path)}, 1


def _build_context_handler(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    return build_context(payload), 0


_HANDLERS: dict[str, tuple[str, Any]] = {
    "build-context": ("circuito_interes", _build_context_handler),
    "validate": ("response_text", validate),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.agent_tools.inference")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    subparsers.add_parser("build-context", help="Emit the context+prompt+allowed envelope for a circuit.")
    subparsers.add_parser("validate", help="Validate a candidate inference response against its context.")
    args = parser.parse_args(argv)

    return cli_dispatch(
        args.verb,
        _HANDLERS,
        module_name="chec_local_interpreter.agent_tools.inference",
    )


if __name__ == "__main__":
    sys.exit(main())
