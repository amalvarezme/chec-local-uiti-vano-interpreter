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
`chec_local_interpreter.expert_alignment` and the standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from chec_local_interpreter.expert_alignment import (
    allowed_dates,
    allowed_pdf_row_indexes,
    allowed_variables,
    compactar_contexto_expert_alignment_para_prompt,
    construir_contexto_expert_alignment,
    construir_prompt_expert_alignment,
    validar_respuesta_expert_alignment,
)

TOOL_VERSION = "expert-alignment-agent-tools/0.1.0"

ARTIFACTS_ROOT = Path("reports/interpretability/artifacts")


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
        "allowed": {
            "dates": sorted(allowed_dates(context)),
            "variables": sorted(allowed_variables(context)),
            "pdf_row_indexes": sorted(allowed_pdf_row_indexes(context)),
            "sources": list(context.get("fuentes_disponibles", [])),
        },
    }


def _write_failure_artifact(circuito: str, response_text: str, errors: list[str]) -> Path:
    artifact_dir = ARTIFACTS_ROOT / (circuito or "unknown")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"invalid_{time.time_ns()}.json"
    artifact_path.write_text(
        json.dumps({"response_text": response_text, "errors": errors}, ensure_ascii=False, indent=2)
    )
    return artifact_path


def validate(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Run the `validate` verb: gate a candidate response through the L1 validator.

    Returns `(result, exit_code)`. On failure, writes the raw response and
    errors under `reports/interpretability/artifacts/{circuito}/` and never
    returns `ok: true`.
    """
    response_text = payload["response_text"]
    context = payload.get("context", {})
    result = validar_respuesta_expert_alignment(response_text, context)
    if result["ok"]:
        return {"ok": True, "data": result["data"]}, 0

    circuito = str(context.get("circuito") or "unknown")
    artifact_path = _write_failure_artifact(circuito, response_text, result["errors"])
    return {"ok": False, "errors": result["errors"], "artifact_path": str(artifact_path)}, 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.agent_tools.expert_alignment")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    subparsers.add_parser("build-context", help="Emit the context+prompt+allowed envelope for a circuit.")
    subparsers.add_parser("validate", help="Validate a candidate expert-alignment response against its context.")
    args = parser.parse_args(argv)

    payload = json.load(sys.stdin)

    if args.verb == "build-context":
        envelope = build_context(payload)
        json.dump(envelope, sys.stdout, ensure_ascii=False)
        return 0

    result, exit_code = validate(payload)
    json.dump(result, sys.stdout, ensure_ascii=False)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
