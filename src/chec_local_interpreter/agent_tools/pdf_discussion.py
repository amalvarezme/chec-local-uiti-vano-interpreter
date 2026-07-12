"""L2 tool-adapter CLI for the pdf-discussion-extraction agent (batch contract, design D5).

This module is a thin stdin/stdout JSON boundary around the deterministic
prompt-template rendering (a plain `{key}` substitution over the
`.claude/skills/pdf-discussion-extraction/prompt/01_pdf_discussion_extractor.md`
playbook, resolved via `chec_local_interpreter.config.agent_prompt_dir`) and
the `chec_local_interpreter.llm_validation.validate_pdf_discussion_row`
validator (L1), applied PER ROW over a whole-PDF batch. It has no import path
to the model training package or the frozen classifier artifact: this agent
classifies every candidate section of one PDF in a single agent turn, it does
not implement any new selection logic (that lives in the deterministic
`chec_local_interpreter.pdf_discussion_pipeline` module, PR A2a).

Verbs:
    build-context   Reads one whole-PDF batch payload from stdin
                     (`fecha_inicio_usuario`, `fecha_fin_usuario`, `nombre_pdf`,
                     `circuito_pdf`, `periodo_general_informe`, `secciones`: a
                     list of `{indice, pagina_inicio, pagina_fin, markdown}`),
                     emits the envelope `{meta, context, prompt}` on stdout --
                     exactly ONE prompt covering every section in the batch.
    validate         Reads `{response_text, circuito_pdf, fecha_inicio_usuario,
                     fecha_fin_usuario}` from stdin JSON. `response_text` is
                     the agent's batched `{"filas": [...], "descartes": [...]}`
                     JSON: `filas` is a list of `include: true`-shaped rows
                     (same per-row shape the notebook's classifier produced),
                     `descartes` is a list of `{"seccion_indice", "reason"}`
                     entries for sections the agent explicitly excluded.
                     Every `filas[]` entry is validated independently via
                     `validate_pdf_discussion_row` (UNCHANGED, imported not
                     redefined) -- a bad row never rejects the whole batch.
                     On any rejection or non-empty `descartes`, writes both
                     under `reports/interpretability/artifacts/pdf-discussion-extraction/{circuito_pdf}/`.

Both verbs read exactly one JSON document from stdin and write exactly one
JSON document to stdout, via the shared `agent_tools.cli_support.dispatch`
0/1/2/3 exit-code contract. No network access, no imports outside
`chec_local_interpreter.config`, `chec_local_interpreter.llm_validation`,
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
from chec_local_interpreter.config import agent_prompt_dir
from chec_local_interpreter.llm_validation import validate_pdf_discussion_row

TOOL_VERSION = "pdf-discussion-agent-tools/0.2.0"

# Relative to the invocation cwd, same convention as
# `agent_tools.historical.ARTIFACTS_ROOT`. Namespaced under its own
# `pdf-discussion-extraction` segment so this agent's failure artifacts can
# never collide with another agent's. Unchanged from the pre-batch CLI.
ARTIFACTS_ROOT = Path("reports/interpretability/artifacts/pdf-discussion-extraction")

_TEMPLATE_PATH = agent_prompt_dir("pdf-discussion-extraction") / "01_pdf_discussion_extractor.md"


def _render_secciones(secciones: list[dict[str, Any]]) -> str:
    """Render every candidate section into one Markdown block, each labeled
    with its `indice` (the id the agent must cite back in `descartes`) and
    page range, so a single prompt can cover the whole batch."""
    blocks = []
    for seccion in secciones:
        indice = seccion.get("indice")
        pagina_inicio = seccion.get("pagina_inicio")
        pagina_fin = seccion.get("pagina_fin")
        markdown = seccion.get("markdown", "")
        blocks.append(
            f"### Seccion {indice} (paginas {pagina_inicio}-{pagina_fin})\n\n{markdown}"
        )
    return "\n\n".join(blocks)


def build_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Build the `build-context` envelope for one whole-PDF batch (design D5, step 4).

    `payload` is the whole-PDF batch context dict (`fecha_inicio_usuario`,
    `fecha_fin_usuario`, `nombre_pdf`, `circuito_pdf`, `periodo_general_informe`,
    `secciones`: a list of `{indice, pagina_inicio, pagina_fin, markdown}`).
    Every top-level key present in `payload` (other than `secciones`, which is
    rendered via `_render_secciones` first) is substituted into the raw
    template's `{key}` placeholders via plain string replacement -- mirroring
    the pre-batch per-fragment `build_context`'s substitution approach, just
    applied to a rendered multi-section block instead of one raw fragment. A
    missing key simply leaves its `{placeholder}` unsubstituted -- this
    function never raises on a missing payload key. Always emits exactly ONE
    prompt, regardless of how many sections the batch contains.
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    secciones = payload.get("secciones") or []

    substitutions = {key: value for key, value in payload.items() if key != "secciones"}
    substitutions["secciones"] = _render_secciones(secciones)

    prompt = template
    for key, value in substitutions.items():
        prompt = prompt.replace("{" + key + "}", str(value))
    prompt = prompt.strip()

    return {
        "meta": {
            "nombre_pdf": payload.get("nombre_pdf", "unknown"),
            "circuito_pdf": payload.get("circuito_pdf", "unknown"),
            "num_secciones": len(secciones),
            "tool_version": TOOL_VERSION,
        },
        "context": payload,
        "prompt": prompt,
    }


def _write_failure_artifact(
    circuito_pdf: str,
    response_text: str,
    rejected: list[dict[str, Any]],
    descartes: list[Any],
) -> Path:
    """Write the raw response plus rejected rows and agent-reported
    `descartes` under `ARTIFACTS_ROOT/{identity}/` (ports the notebook's
    `invalid_llm_outputs.json`, one file per batch).

    Uses `canonical_circuit_identity` (sanitize + normalize), the same
    identity function every other circuit-derived artifact path in this
    codebase uses, so this agent's failure-artifact directory is
    deterministic and collision-safe regardless of how the raw
    `circuito_pdf` value is cased or punctuated.
    """
    artifacts_root = ARTIFACTS_ROOT.resolve()
    safe_name = canonical_circuit_identity(circuito_pdf)
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
        json.dumps(
            {"response_text": response_text, "rejected": rejected, "descartes": descartes},
            ensure_ascii=False,
            indent=2,
        ),
    )
    return artifact_path


def validate(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Run the `validate` verb: gate a candidate BATCH response, row by row.

    `payload["response_text"]` must parse as a JSON object shaped
    `{"filas": [<include:true row>...], "descartes": [{"seccion_indice",
    "reason"}...]}`. Every `filas[]` entry is validated independently via
    `validate_pdf_discussion_row` (UNCHANGED -- the anti-spoofing
    `Circuito`-forcing and date/overlap checks are reused exactly as-is, not
    reimplemented here). A bad row is collected into `rejected`, never
    discarding the rest of the batch (`ok: True`, exit code 0, as long as the
    top-level `{filas, descartes}` envelope itself parsed). `descartes` is
    the agent's own explicit exclusions (a section it chose not to turn into
    a row) -- passed straight through, never counted as `rejected`.

    Returns `(result, exit_code)`:
      - exit 1 (`ok: False`) only when `response_text` itself is not a valid
        JSON object (the batch envelope could not even be parsed).
      - exit 0 (`ok: True`) otherwise -- the batch as a whole is never
        rejected wholesale for containing some invalid rows.

    On any rejection or non-empty `descartes`, writes both under
    `reports/interpretability/artifacts/pdf-discussion-extraction/{circuito_pdf}/`
    and reports that path via `artifact_path` (`None` when there was nothing
    to persist).
    """
    response_text = payload["response_text"]
    circuito_pdf = payload.get("circuito_pdf", "")
    fecha_inicio_usuario = payload.get("fecha_inicio_usuario", "")
    fecha_fin_usuario = payload.get("fecha_fin_usuario", "")

    try:
        parsed = json.loads(response_text or "")
    except json.JSONDecodeError as exc:
        artifact_path = _write_failure_artifact(circuito_pdf or "unknown", response_text, [], [])
        return {
            "ok": False,
            "rows": [],
            "rejected": [],
            "errors": [f"JSON invalido: {exc}"],
            "artifact_path": str(artifact_path),
        }, 1

    if not isinstance(parsed, dict):
        artifact_path = _write_failure_artifact(circuito_pdf or "unknown", response_text, [], [])
        return {
            "ok": False,
            "rows": [],
            "rejected": [],
            "errors": ["La respuesta debe ser un objeto JSON con 'filas' y 'descartes'."],
            "artifact_path": str(artifact_path),
        }, 1

    filas = parsed.get("filas", [])
    filas = filas if isinstance(filas, list) else []
    descartes = parsed.get("descartes", [])
    descartes = descartes if isinstance(descartes, list) else []

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in filas:
        row_response_text = json.dumps(row, ensure_ascii=False)
        result = validate_pdf_discussion_row(
            row_response_text,
            circuito_pdf=circuito_pdf,
            fecha_inicio_usuario=fecha_inicio_usuario,
            fecha_fin_usuario=fecha_fin_usuario,
        )
        if result["ok"]:
            accepted.append(result["data"])
        else:
            rejected.append({"row": row, "errors": result["errors"]})

    artifact_path: str | None = None
    if rejected or descartes:
        written = _write_failure_artifact(circuito_pdf or "unknown", response_text, rejected, descartes)
        artifact_path = str(written)

    return {
        "ok": True,
        "rows": accepted,
        "rejected": rejected,
        "artifact_path": artifact_path,
    }, 0


def _build_context_handler(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    return build_context(payload), 0


_HANDLERS: dict[str, tuple[str, Any]] = {
    "build-context": ("secciones", _build_context_handler),
    "validate": ("response_text", validate),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.agent_tools.pdf_discussion")
    subparsers = parser.add_subparsers(dest="verb", required=True)
    subparsers.add_parser("build-context", help="Emit the context+prompt envelope for one PDF's candidate sections.")
    subparsers.add_parser("validate", help="Validate a candidate batch {filas, descartes} response, row by row.")
    args = parser.parse_args(argv)

    return cli_dispatch(
        args.verb,
        _HANDLERS,
        module_name="chec_local_interpreter.agent_tools.pdf_discussion",
    )


if __name__ == "__main__":
    sys.exit(main())
