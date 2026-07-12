"""L2 tool-adapter CLI for the auto-simulator agent.

This module is a thin stdin/stdout JSON boundary around the already-built,
deterministic auto-simulator context (assembled upstream — equivalent to the
deprecated notebook's `_compact_auto_simulation_context()` output) and the
`chec_local_interpreter.llm_validation.validate_auto_simulator_response`
validator (L1). It has no import path to the model training package or the
frozen classifier artifact: it packages an already-built context and gates
output through the existing required-keys/list-shape validator, it does not
implement any new selection or simulation logic.

Verbs:
    build-context   Reads the already-assembled compact auto-simulator
                    context JSON from stdin (equivalent to the notebook's
                    `_compact_auto_simulation_context()` output), emits the
                    envelope `{meta, context, prompt}` on stdout. Unlike
                    `historical`/`expert-alignment`, this agent has no
                    provenance validator, so the envelope has no `allowed`
                    block.
    validate        Reads `{response_text}` from stdin JSON, runs
                    `validate_auto_simulator_response`. On failure, writes
                    the raw output plus errors under
                    `reports/interpretability/artifacts/auto-simulator/run/`.

Both verbs read exactly one JSON document from stdin and write exactly one
JSON document to stdout, via the shared `agent_tools.cli_support.dispatch`
0/1/2/3 exit-code contract. No network access, no imports outside
`chec_local_interpreter.llm_skills`, `chec_local_interpreter.llm_validation`,
the sibling `agent_tools._atomic_io` and `agent_tools.cli_support`
shared-utility modules, and the standard library.
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
from chec_local_interpreter.llm_skills import assemble_skill_bundle
from chec_local_interpreter.llm_validation import validate_auto_simulator_response

TOOL_VERSION = "auto-simulator-agent-tools/0.1.0"

# Relative to the invocation cwd, same convention as
# `agent_tools.historical.ARTIFACTS_ROOT`. `build_context()`'s payload has no
# reliably-present circuit identity to namespace failure artifacts by (unlike
# `historical`/`expert-alignment`), but its `meta.circuito` is available once
# `build-context` has run — `validate()` below uses that, when the caller
# passes it back, as the artifact subdirectory (sanitized the same way
# `historical`/`pdf_discussion` do), falling back to a single fixed `run`
# subdirectory only when no `circuito` is supplied.
ARTIFACTS_ROOT = Path("reports/interpretability/artifacts/auto-simulator")

# Same "REGLAS CRÍTICAS ADICIONALES" block the deprecated notebook's
# `_auto_simulator_prompt()` appends after the skill bundle (minus the
# previous-errors text: a retry with accumulated errors is the invoking
# coding agent's own responsibility per the Skill's documented run sequence,
# not something this CLI generates on its behalf).
_EXTRA_RULES = """REGLAS CRÍTICAS ADICIONALES:
- Devuelve SOLO JSON válido; sin markdown, sin ```json, sin <think>, sin texto adicional.
- Cierra todos los arreglos y el objeto raíz.
- Máximo 5 ítems por lista.
- Usa solo la tabla y metadata entregadas. Si la tabla está vacía, responde con limitaciones basadas en esa ausencia, no inventes resultados."""


def build_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the `build-context` envelope from the already-assembled compact context.

    `payload` IS the deterministic, already-compacted auto-simulator context
    (equivalent to the deprecated notebook's `_compact_auto_simulation_context()`
    output: keys like `contexto`, `metadata`, `variables_priorizadas`,
    `tabla_simulador_automatico`, ...) — this CLI never performs its own
    selection or simulation. Its shape is treated as opaque, the same way
    `agent_tools.historical.build_context` treats its own context: no key
    other than `contexto.circuito` (used only to label the envelope's `meta`)
    is inspected or required here.
    """
    context = payload
    skill_bundle = assemble_skill_bundle(profile="auto_simulator")
    prompt = (
        f"{skill_bundle}\n\n{_EXTRA_RULES}\n\n"
        "Contexto compacto del simulador automático:\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
    )

    contexto_block = context.get("contexto")
    circuito = contexto_block.get("circuito") if isinstance(contexto_block, dict) else None
    circuito = str(circuito) if circuito else "unknown"

    return {
        "meta": {
            "circuito": circuito,
            "tool_version": TOOL_VERSION,
        },
        "context": context,
        "prompt": prompt,
    }


def validate(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Run the `validate` verb: gate a candidate response through the required-keys/list-shape validator.

    `payload` accepts an optional `circuito` key (the same value returned in
    `build_context()`'s `meta.circuito`). When present and non-empty, failure
    artifacts are written under that circuit's own sanitized subdirectory
    (via `canonical_circuit_identity`, matching `historical`/`pdf_discussion`);
    otherwise they fall back to the fixed `run` subdirectory, so this stays
    backward compatible with callers that only send `response_text`.

    Returns `(result, exit_code)`. On failure, writes the raw response and
    errors under `reports/interpretability/artifacts/auto-simulator/{subdir}/`
    and never returns `ok: true`.
    """
    response_text = payload["response_text"]
    circuito = payload.get("circuito")
    result = validate_auto_simulator_response(response_text)

    if result["ok"]:
        return {"ok": True, "data": result["data"]}, 0

    subdir = canonical_circuit_identity(circuito) if circuito and str(circuito).strip() else "run"
    artifacts_root = ARTIFACTS_ROOT.resolve()
    artifact_dir = (ARTIFACTS_ROOT / subdir).resolve()
    # Defense in depth: sanitization above should already guarantee containment,
    # but never mkdir/write outside ARTIFACTS_ROOT even if that guarantee is
    # ever weakened by a future change (same pattern as `historical.py`'s and
    # `pdf_discussion.py`'s `_write_failure_artifact`).
    if artifact_dir != artifacts_root and artifacts_root not in artifact_dir.parents:
        artifact_dir = artifacts_root / "run"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"invalid_{time.time_ns()}.json"
    _atomic_write_text(
        artifact_path,
        json.dumps({"response_text": response_text, "errors": result["errors"]}, ensure_ascii=False, indent=2),
    )
    return {"ok": False, "errors": result["errors"], "artifact_path": str(artifact_path)}, 1


def _build_context_handler(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    return build_context(payload), 0


_HANDLERS: dict[str, tuple[str, Any]] = {
    "build-context": ("contexto", _build_context_handler),
    "validate": ("response_text", validate),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.agent_tools.auto_simulator")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    subparsers.add_parser("build-context", help="Emit the context+prompt envelope for the auto-simulator table.")
    subparsers.add_parser("validate", help="Validate a candidate auto-simulator response against the required shape.")
    args = parser.parse_args(argv)

    return cli_dispatch(
        args.verb,
        _HANDLERS,
        module_name="chec_local_interpreter.agent_tools.auto_simulator",
    )


if __name__ == "__main__":
    sys.exit(main())
