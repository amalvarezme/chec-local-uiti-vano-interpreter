"""L1 strict validator for the inference/MGCECDL agent (Slice A, Phase 2).

This module REPLACES reliance on the frozen, weak
`chec_impacto.interpretability.circuit_analysis.validar_respuesta_inferencia`
(name-completeness-only check over `escenarios`/`discusion_grafos`, no schema,
no guardrails, no provenance) with a two-stage gate reaching the same rigor as
`llm_validation.validate_llm_response` (historical/base) and
`expert_alignment.validar_respuesta_expert_alignment`:

    1. `validar_respuesta_inferencia_strict` — JSON-Schema conformance against
       `llm/prompts/inference.output_schema.json`, plus domain guardrails
       (no forbidden causal-certainty phrasing; every date/`critical_point_id`
       -shaped and scenario-name token referenced in the free text of the
       response must resolve against the circuit's own inference context).
    2. `validar_provenance_inferencia` — the additive, optional-per-item
       provenance check, built on the shared `validar_provenance_generico`
       core extracted in Phase 1 (`llm_validation.py`), parameterized with
       this agent's own id, playbook rule ids, and allowed-reference
       resolver (dates + critical-point ids + variables + scenario names).

The frozen `chec_impacto.interpretability.circuit_analysis` module (and its
weak validator) is left completely untouched — this is a new, additive L1
module living inside `chec_local_interpreter`, off the frozen subpackage,
per the design (`sdd/report-command-pipeline`).
"""

from __future__ import annotations

import re
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only in minimal environments
    Draft202012Validator = None

from chec_local_interpreter.config import llm_root
from chec_local_interpreter.llm_validation import parse_llm_json, validar_provenance_generico

INFERENCE_AGENT_ID = "inference"

# Mirrors `llm/skills_inference/*.md` filenames (stripped of the `.md`
# suffix), same convention as `BASE_PROVENANCE_RULES` /
# `EXPERT_ALIGNMENT_PROVENANCE_RULES`. Kept in sync with
# `.claude/agents/rules/invariants.md` once the inference role/Skill land
# (Phase 4).
INFERENCE_PROVENANCE_RULES = frozenset({
    "01_structured_context_builder",
    "02_circuit_scenario_interpreter",
    "03_uiti_vano_behavior_explainer",
    "04_graph_connectivity_guardrails",
    "05_llm_output_validator",
    "06_inference_output_contract",
})

_OUTPUT_SCHEMA_FILE = "inference.output_schema.json"

# Domain-guardrail phrasing to reject regardless of schema conformance
# (mirrors `llm/skills_inference/05_llm_output_validator.md`'s "Validaciones
# de lenguaje" table plus the spec's own literal example scenario).
FORBIDDEN_CAUSAL_PHRASES = (
    "demonstrates that",
    "demuestra el origen del evento",
    "demuestra que",
    "inferencia uso el grafo",
    "inferencia usó el grafo",
    "la variable aislada explica el resultado",
)

_CP_REF_RE = re.compile(r"^cp-\d{4}-\d{2}-\d{2}$")
_DATE_REF_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
_TEXT_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_TEXT_CP_REF_RE = re.compile(r"\bcp-\d{4}-\d{2}-\d{2}\b")


def _load_schema() -> dict[str, Any]:
    import json

    path = llm_root() / "prompts" / _OUTPUT_SCHEMA_FILE
    if not path.exists():
        raise FileNotFoundError(f"Inference output schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_flatten_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_flatten_strings(item))
        return strings
    return []


# --- Public context accessors (reused by build_context/validate in
# `agent_tools/inference.py`, mirroring historical's `allowed_dates`/
# `allowed_critical_point_ids`/`unavailable_columns` re-exports). ---


def allowed_dates(context: dict[str, Any]) -> set[str]:
    """Every ISO date the inference context legitimately carries.

    Sources: the top-level `fechas_interes` list, each escenario's own
    `fechas_interes`, and the overall analysis window (`fecha_inicio`/
    `fecha_fin`).
    """
    dates: set[str] = set()
    for value in context.get("fechas_interes", []) or []:
        if value:
            dates.add(str(value))
    for escenario in context.get("escenarios", []) or []:
        if not isinstance(escenario, dict):
            continue
        for value in escenario.get("fechas_interes", []) or []:
            if value:
                dates.add(str(value))
    if context.get("fecha_inicio"):
        dates.add(str(context["fecha_inicio"]))
    if context.get("fecha_fin"):
        dates.add(str(context["fecha_fin"]))
    return dates


def allowed_critical_point_ids(context: dict[str, Any]) -> set[str]:
    """Derived `cp-YYYY-MM-DD` ids for every date in `allowed_dates`.

    Unlike the historical/base context, the inference context package
    (`circuit_analysis.construir_contexto_inferencia`) does not carry its own
    explicit `critical_point_id` list — its dates of interest already
    originate from the same critical points upstream, so the `cp-` id
    universe is derived from `allowed_dates` using the same `cp-{date}`
    convention historical/expert-alignment already use.
    """
    return {f"cp-{date}" for date in allowed_dates(context)}


def allowed_variables(context: dict[str, Any]) -> set[str]:
    """The inference agent's citable variable universe: `context["features"]`."""
    return {str(feature).strip().upper() for feature in context.get("features", []) or [] if str(feature).strip()}


def allowed_scenario_names(context: dict[str, Any]) -> set[str]:
    """Every scenario name the inference context actually built."""
    return {
        str(item.get("nombre"))
        for item in context.get("escenarios", []) or []
        if isinstance(item, dict) and item.get("nombre")
    }


def _guardrail_errors(data: dict[str, Any], context: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    full_text_blob = "\n".join(_flatten_strings(data))
    lowered_blob = full_text_blob.lower()

    for phrase in FORBIDDEN_CAUSAL_PHRASES:
        if phrase in lowered_blob:
            errors.append(f"Forbidden causal-certainty phrase referenced: {phrase!r}")

    dates_allowed = allowed_dates(context)
    for date in _TEXT_DATE_RE.findall(full_text_blob):
        if date not in dates_allowed:
            errors.append(f"Referenced date outside context: {date}")

    cp_ids_allowed = allowed_critical_point_ids(context)
    for cp_ref in _TEXT_CP_REF_RE.findall(full_text_blob):
        if cp_ref not in cp_ids_allowed:
            errors.append(f"Referenced critical_point_id outside context: {cp_ref}")

    scenario_names_allowed = allowed_scenario_names(context)
    for escenario in data.get("escenarios", []) or []:
        if not isinstance(escenario, dict):
            continue
        nombre = escenario.get("nombre")
        if nombre is not None and str(nombre) not in scenario_names_allowed:
            errors.append(f"Escenario inventado fuera del contexto recibido: {nombre}")

    return errors


def validar_respuesta_inferencia_strict(response_text: str, context: dict[str, Any]) -> dict[str, Any]:
    """Two-stage-ready schema+guardrail validator for the inference agent.

    Returns `{"ok": bool, "data": dict | None, "errors": list[str]}` — the
    same shape `validate()` (agent_tools/inference.py) expects before running
    the additive `validar_provenance_inferencia` stage.
    """
    try:
        data = parse_llm_json(response_text)
    except Exception as exc:  # noqa: BLE001 - malformed/non-JSON model output
        return {"ok": False, "data": None, "errors": [f"Invalid JSON: {exc}"]}

    if not isinstance(data, dict):
        return {"ok": False, "data": None, "errors": ["La respuesta debe ser un objeto JSON."]}

    errors: list[str] = []
    schema = _load_schema()
    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(data), key=lambda item: item.path):
            location = ".".join(str(part) for part in error.path) or "<root>"
            errors.append(f"{location}: {error.message}")
    else:  # pragma: no cover - exercised only in minimal environments
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"<root>: missing required property {key}")

    errors.extend(_guardrail_errors(data, context))
    return {"ok": not errors, "data": data if not errors else data, "errors": errors}


def _validate_provenance_data_ref_inferencia(
    ref: Any,
    *,
    allowed_dates_set: set[str],
    allowed_critical_point_ids_set: set[str],
    allowed_variable_tokens: set[str],
    allowed_scenario_names_set: set[str],
) -> str | None:
    """Resolve one inference-agent `data_ref` entry against its allowed universe.

    A `data_ref` entry is either a `cp-YYYY-MM-DD` critical-point id, an ISO
    date, an exact scenario name (`context["escenarios"][*]["nombre"]`,
    matched verbatim since scenario names contain spaces/punctuation), or a
    `features` variable name (case-insensitive) — fails closed for anything
    else.
    """
    text = str(ref).strip()

    if _CP_REF_RE.match(text):
        if text not in allowed_critical_point_ids_set:
            return f"provenance.data_ref cites an unknown critical_point_id: {text}"
        return None

    if _DATE_REF_RE.match(text):
        if text not in allowed_dates_set:
            return f"provenance.data_ref cites a date outside the allowed context: {text}"
        return None

    if text in allowed_scenario_names_set:
        return None

    token = text.upper()
    if not token or token not in allowed_variable_tokens:
        return f"provenance.data_ref cites an unknown variable or scenario: {text or ref!r}"
    return None


def validar_provenance_inferencia(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Additively validate per-item `provenance` objects, when present.

    Provenance is optional per item (backwards compatible): an `escenarios`
    or `discusion_grafos` item without a `provenance` key is never flagged.
    When present, `provenance` must be `{data_ref, agent, rule}` with every
    `data_ref` entry resolving to the circuit's already-validated allowed
    dates/critical-point-ids/variables/scenario-names, `agent` naming the
    producing role (`INFERENCE_AGENT_ID`), and `rule` naming an entry from
    the hermetic `INFERENCE_PROVENANCE_RULES` allow-list.
    """
    allowed_dates_set = allowed_dates(context)
    allowed_critical_point_ids_set = allowed_critical_point_ids(context)
    allowed_variable_tokens = allowed_variables(context)
    allowed_scenario_names_set = allowed_scenario_names(context)

    def resolve_data_ref(ref: Any) -> str | None:
        return _validate_provenance_data_ref_inferencia(
            ref,
            allowed_dates_set=allowed_dates_set,
            allowed_critical_point_ids_set=allowed_critical_point_ids_set,
            allowed_variable_tokens=allowed_variable_tokens,
            allowed_scenario_names_set=allowed_scenario_names_set,
        )

    return validar_provenance_generico(
        data,
        sections=("escenarios", "discusion_grafos"),
        agent_id=INFERENCE_AGENT_ID,
        allowed_rules=INFERENCE_PROVENANCE_RULES,
        resolve_data_ref=resolve_data_ref,
        error_not_object=lambda: "provenance must be an object.",
        error_bad_agent=lambda agent: f"provenance.agent must be '{INFERENCE_AGENT_ID}', got: {agent!r}",
        error_bad_rule=lambda rule: f"provenance.rule not in the allowed rule list: {rule!r}",
        error_empty_data_ref=lambda: "provenance.data_ref must be a non-empty list.",
    )
