from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only in minimal environments
    Draft202012Validator = None

from chec_local_interpreter.llm_contracts import load_output_schema
from chec_local_interpreter.pdf_discussion_pipeline import COLUMNAS_FINALES as _PDF_DISCUSSION_COLUMNAS_FINALES

@dataclass
class ValidationResult:
    ok: bool
    data: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


def parse_llm_json(response_text: str) -> dict[str, Any]:
    text = response_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1]
    data = json.loads(text)
    return _strip_schema_meta_keys(data)


def _strip_schema_meta_keys(data: Any) -> Any:
    """Drop JSON-Schema meta-keywords the model tends to echo at the object root.

    The output schema is embedded verbatim in the prompt, so weaker models copy its
    ``$schema``/``$id`` metadata into their answer. Under ``additionalProperties: false``
    that turns an otherwise-valid answer into a hard validation failure, so we remove any
    top-level ``$``-prefixed key before validation.
    """
    if isinstance(data, dict):
        return {key: value for key, value in data.items() if not str(key).startswith("$")}
    return data


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


def _context_dates(context: dict[str, Any]) -> set[str]:
    dates = {
        str(item.get("fecha_dia"))
        for item in context.get("daily_series", [])
        if isinstance(item, dict) and item.get("fecha_dia")
    }
    dates.update(
        str(item.get("fecha_dia"))
        for item in context.get("critical_points", [])
        if isinstance(item, dict) and item.get("fecha_dia")
    )
    for item in context.get("critical_periods", []):
        if not isinstance(item, dict):
            continue
        if item.get("start_date"):
            dates.add(str(item.get("start_date")))
        if item.get("end_date"):
            dates.add(str(item.get("end_date")))
    dates.update(
        str(item.get("d"))
        for item in context.get("daily", [])
        if isinstance(item, dict) and item.get("d")
    )
    # Also allow the overall analysis window start and end dates
    window = context.get("window_summary")
    if isinstance(window, dict):
        if window.get("start_date"):
            dates.add(str(window.get("start_date")))
        if window.get("end_date"):
            dates.add(str(window.get("end_date")))
    metadata = context.get("metadata")
    if isinstance(metadata, dict):
        if metadata.get("start"):
            dates.add(str(metadata.get("start")))
        if metadata.get("end"):
            dates.add(str(metadata.get("end")))
            
    return dates


def _critical_point_ids(context: dict[str, Any]) -> set[str]:
    ids = {
        str(item.get("critical_point_id"))
        for item in context.get("critical_points", [])
        if isinstance(item, dict) and item.get("critical_point_id")
    }
    ids.update(
        str(item.get("critical_period_id"))
        for item in context.get("critical_periods", [])
        if isinstance(item, dict) and item.get("critical_period_id")
    )
    return ids


def _unavailable_columns(context: dict[str, Any]) -> set[str]:
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    columns = list(metadata.get("unavailable_optional_columns", []))
    columns.extend(metadata.get("unavailable_cols", []))
    return {str(column).upper() for column in columns}


def _guardrail_errors(data: dict[str, Any], context: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    
    # For the rest of the checks (dates, IDs, etc.), use the full text
    full_text_blob = "\n".join(_flatten_strings(data)).lower()
    allowed_dates = _context_dates(context)
    for date in re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", full_text_blob):
        if date not in allowed_dates:
            errors.append(f"Referenced date outside context: {date}")

    allowed_ids = _critical_point_ids(context)
    for referenced in re.findall(r"\bcp-\d{4}-\d{2}-\d{2}\b", full_text_blob):
        if referenced not in allowed_ids:
            errors.append(f"Referenced critical_point_id outside context: {referenced}")
    for finding in data.get("key_findings", []):
        if not isinstance(finding, dict):
            continue
        for section in ("evidence", "referenced_events"):
            for item in finding.get(section, []):
                if not isinstance(item, dict):
                    continue
                item_date = item.get("date")
                item_id = item.get("critical_point_id")
                if item_date and str(item_date) not in allowed_dates:
                    errors.append(f"Referenced date outside context: {item_date}")
                if item_id and str(item_id) not in allowed_ids:
                    errors.append(f"Referenced critical_point_id outside context: {item_id}")

    unavailable = _unavailable_columns(context)
    for column in unavailable:
        pattern = rf"\b{re.escape(column.lower())}\b"
        if re.search(pattern, full_text_blob):
            errors.append(f"Unavailable column referenced as present: {column}")

    if unavailable and not data.get("data_gaps"):
        errors.append("Output must include data_gaps when optional variables are unavailable.")

    return errors


def validate_llm_response(
    response_text: str,
    context: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> ValidationResult:
    errors: list[str] = []
    try:
        data = parse_llm_json(response_text)
    except json.JSONDecodeError as exc:
        return ValidationResult(ok=False, data=None, errors=[f"Invalid JSON: {exc}"])

    schema = schema or load_output_schema()
    if Draft202012Validator is not None:
        validator = Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(data), key=lambda item: item.path):
            location = ".".join(str(part) for part in error.path) or "<root>"
            errors.append(f"{location}: {error.message}")
    else:
        required = schema.get("required", [])
        for key in required:
            if key not in data:
                errors.append(f"<root>: missing required property {key}")
    errors.extend(_guardrail_errors(data, context))
    return ValidationResult(ok=not errors, data=data if not errors else data, errors=errors)


# --- Public context accessors (Slice 1b: reused by the historical agent's L2 CLI) ---
#
# Wrap the existing private helpers rather than duplicating them, so the base/
# historical agent's `build-context` envelope and provenance validator stay
# consistent with the exact same allow-lists the schema/guardrail validator
# already enforces (mirrors `expert_alignment.py`'s `allowed_dates`/
# `allowed_variables`/`allowed_pdf_row_indexes` public re-exports).


def allowed_dates(context: dict[str, Any]) -> set[str]:
    """Public re-export of `_context_dates` for reuse by the agent-tools CLI layer."""
    return _context_dates(context)


def allowed_critical_point_ids(context: dict[str, Any]) -> set[str]:
    """Public re-export of `_critical_point_ids` for reuse by the agent-tools CLI layer."""
    return _critical_point_ids(context)


def unavailable_columns(context: dict[str, Any]) -> set[str]:
    """Public re-export of `_unavailable_columns` for reuse by the agent-tools CLI layer."""
    return _unavailable_columns(context)


# --- Provenance/traceability for the historical/base agent (ADR-7) ---------
#
# Mirrors `expert_alignment.py`'s `validar_provenance_expert_alignment`: a
# small, hermetic allow-list of playbook rule ids checked in-code (no file
# read), and a producing-agent id constant. Kept in sync with
# `.claude/agents/rules/invariants.md` and the 7
# `.claude/skills/historical/prompt/*.md` base playbooks (ids derived by
# stripping the `NN_` prefix and `.md` suffix,
# preserving `assemble_skill_bundle(profile="base")` order).
BASE_AGENT_ID = "historical"

BASE_PROVENANCE_RULES = frozenset({
    "01_structured_context_builder",
    "02_critical_point_interpreter",
    "03_uiti_vano_behavior_explainer",
    "04_domain_grounding_guardrails",
    "05_llm_output_validator",
    "06_base_repair",
    "07_base_output_contract",
})

_CP_REF_RE = re.compile(r"^cp-\d{4}-\d{2}-\d{2}$")
_BASE_DATE_REF_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")


def _allowed_variable_tokens(context: dict[str, Any]) -> set[str]:
    """The base agent's citable variable universe: every variable name across
    `context["domain"]["variable_groups"]` (the same domain payload the
    context builder always attaches), upper-cased for case-insensitive
    matching against a `data_ref` token."""
    domain = context.get("domain") if isinstance(context.get("domain"), dict) else {}
    groups = domain.get("variable_groups") if isinstance(domain.get("variable_groups"), dict) else {}
    tokens: set[str] = set()
    for group in groups.values():
        if not isinstance(group, dict):
            continue
        for variable in group.get("variables", []):
            if variable:
                tokens.add(str(variable).upper())
    return tokens


def _validate_provenance_data_ref_base(
    ref: Any,
    *,
    allowed_dates_set: set[str],
    allowed_critical_point_ids_set: set[str],
    allowed_variable_tokens: set[str],
    unavailable: set[str],
) -> str | None:
    """Resolve one base-agent `data_ref` entry against its allowed universe.

    Returns an error message naming the offending reference, or `None` if it
    resolves. A `data_ref` entry is either a `cp-YYYY-MM-DD` critical-point
    id, an ISO date (`YYYY-MM-DD`), or a domain variable name — fails closed
    (rejected) for anything else, including a variable explicitly marked
    unavailable for this context.
    """
    text = str(ref).strip()

    if _CP_REF_RE.match(text):
        if text not in allowed_critical_point_ids_set:
            return f"provenance.data_ref cites an unknown critical_point_id: {text}"
        return None

    if _BASE_DATE_REF_RE.match(text):
        if text not in allowed_dates_set:
            return f"provenance.data_ref cites a date outside the allowed context: {text}"
        return None

    token = text.upper()
    if not token or token in unavailable or token not in allowed_variable_tokens:
        return f"provenance.data_ref cites an unknown or unavailable variable: {text or ref!r}"
    return None


def validar_provenance_generico(
    data: dict[str, Any],
    *,
    sections: tuple[str, ...],
    agent_id: str,
    allowed_rules: frozenset[str],
    resolve_data_ref: Callable[[Any], str | None],
    error_not_object: Callable[[], str],
    error_bad_agent: Callable[[Any], str],
    error_bad_rule: Callable[[Any], str],
    error_empty_data_ref: Callable[[], str],
) -> dict[str, Any]:
    """Shared provenance-validation core (ADR-7), reused by every agent's
    `validar_provenance_*` wrapper (base/historical, expert-alignment, and
    inference — see design `sdd/report-command-pipeline`).

    Provenance is optional per item (backwards compatible with responses that
    predate the provenance contract): an item without a `provenance` key is
    never flagged. When present, `provenance` must be
    `{data_ref, agent, rule}` with every `data_ref` entry resolving through
    the caller-supplied `resolve_data_ref` (each agent's own allowed universe
    of dates/ids/variables/etc.), `agent` matching `agent_id`, and `rule`
    naming an entry from `allowed_rules`.

    Message text is fully delegated to the `error_*` callables so each
    wrapper can keep its own exact (and possibly differently-worded/localized)
    error strings — this function only owns the traversal/accumulation logic,
    not the wording, so migrating existing validators onto it is behavior-
    preserving byte-for-byte.
    """
    errors: list[str] = []
    for section_name in sections:
        section = data.get(section_name, [])
        if not isinstance(section, list):
            continue
        for item in section:
            if not isinstance(item, dict):
                continue
            provenance = item.get("provenance")
            if provenance is None:
                continue
            if not isinstance(provenance, dict):
                errors.append(f"{section_name}: {error_not_object()}")
                continue

            agent = provenance.get("agent")
            if agent != agent_id:
                errors.append(f"{section_name}: {error_bad_agent(agent)}")

            rule = provenance.get("rule")
            if rule not in allowed_rules:
                errors.append(f"{section_name}: {error_bad_rule(rule)}")

            data_ref = provenance.get("data_ref")
            if not isinstance(data_ref, list) or not data_ref:
                errors.append(f"{section_name}: {error_empty_data_ref()}")
                continue
            for ref in data_ref:
                error = resolve_data_ref(ref)
                if error:
                    errors.append(f"{section_name}: {error}")

    return {"ok": not errors, "errors": errors}


def validar_provenance_base(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Additively validate per-`key_finding` `provenance` objects, when present.

    Provenance is optional per item (backwards compatible with responses that
    predate the provenance contract): a `key_finding` without a `provenance`
    key is never flagged. When present, `provenance` must be
    `{data_ref, agent, rule}` with every `data_ref` entry resolving to the
    circuit's already-validated allowed dates/critical-point-ids/variables,
    `agent` naming the producing role (`BASE_AGENT_ID`), and `rule` naming an
    entry from the hermetic `BASE_PROVENANCE_RULES` allow-list.
    """
    allowed_dates_set = allowed_dates(context)
    allowed_critical_point_ids_set = allowed_critical_point_ids(context)
    allowed_variable_tokens = _allowed_variable_tokens(context)
    unavailable = unavailable_columns(context)

    def resolve_data_ref(ref: Any) -> str | None:
        return _validate_provenance_data_ref_base(
            ref,
            allowed_dates_set=allowed_dates_set,
            allowed_critical_point_ids_set=allowed_critical_point_ids_set,
            allowed_variable_tokens=allowed_variable_tokens,
            unavailable=unavailable,
        )

    return validar_provenance_generico(
        data,
        sections=("key_findings",),
        agent_id=BASE_AGENT_ID,
        allowed_rules=BASE_PROVENANCE_RULES,
        resolve_data_ref=resolve_data_ref,
        error_not_object=lambda: "provenance must be an object.",
        error_bad_agent=lambda agent: f"provenance.agent must be '{BASE_AGENT_ID}', got: {agent!r}",
        error_bad_rule=lambda rule: f"provenance.rule not in the allowed rule list: {rule!r}",
        error_empty_data_ref=lambda: "provenance.data_ref must be a non-empty list.",
    )


def save_invalid_output(response_text: str, errors: list[str], output_dir: str | Path, timestamp: str) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / f"invalid_llm_output_{timestamp}.txt"
    errors_path = directory / f"llm_validation_errors_{timestamp}.json"
    raw_path.write_text(response_text, encoding="utf-8")
    errors_path.write_text(json.dumps({"errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_path, errors_path


# --- Auto-simulator response validator ---------------------------------
#
# Ported verbatim from `_validate_auto_simulator_response`, defined inline in
# the deprecated `notebooks/core/02_local_uiti_vano_interpretability_v3.ipynb`
# ("10.2 Simulador automático mínimo/máximo" section). Reuses `parse_llm_json`
# (already defined above in this module) rather than reimplementing JSON
# extraction — the notebook cell already imported and called the same
# function.


def validate_auto_simulator_response(response_text: str) -> dict[str, Any]:
    """Validate a candidate auto-simulator LLM response.

    Checks that `response_text` parses as a JSON object containing the seven
    required keys (`titulo`, `resumen`, `variables_mas_sensibles`,
    `patrones_minimo_maximo`, `hallazgos_para_criticidad`, `limitaciones`,
    `contexto_reutilizado`), and that every key besides `titulo` is a list
    when present. Returns `{"ok": bool, "data": dict | None, "errors": [...]}`.
    """
    required_keys = {
        "titulo",
        "resumen",
        "variables_mas_sensibles",
        "patrones_minimo_maximo",
        "hallazgos_para_criticidad",
        "limitaciones",
        "contexto_reutilizado",
    }
    try:
        data = parse_llm_json(response_text or "")
    except Exception as exc:  # noqa: BLE001 - mirrors the notebook's broad catch
        return {"ok": False, "data": None, "errors": [f"JSON inválido: {exc}"]}
    if not isinstance(data, dict):
        return {"ok": False, "data": None, "errors": ["La respuesta debe ser un objeto JSON."]}
    missing_keys = sorted(required_keys - set(data))
    errors = [f"Faltan claves requeridas: {missing_keys}"] if missing_keys else []
    for key in [
        "resumen",
        "variables_mas_sensibles",
        "patrones_minimo_maximo",
        "hallazgos_para_criticidad",
        "limitaciones",
        "contexto_reutilizado",
    ]:
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key} debe ser una lista.")
    return {"ok": not errors, "data": data, "errors": errors}


# --- PDF-discussion-extraction row validator ----------------------------
#
# `_MESES`/`_parse_fecha`/`_iso_fecha`/`_overlaps` and `COLUMNAS_FINALES` are
# ported verbatim from `notebooks/core/01_pdf_discussion_table_from_pdfs.ipynb`
# (deprecated), prefixed with `_` to match this module's existing private-
# helper convention (`_context_dates`, `_critical_point_ids`, ...).
# `validate_pdf_discussion_row` combines the notebook's `validate_llm_row`
# with the `parsed["Circuito"] = circuito_pdf` forcing step the notebook
# performs just before calling it, so the "never trust the LLM's own
# `Circuito` value" invariant lives in one place.

# Single source of truth: `pdf_discussion_pipeline.COLUMNAS_FINALES` (design
# D5's new canonical home for the deterministic PDF-discussion pipeline). PR
# A2a temporarily defined its own copy here alongside `expert_alignment`'s
# `REQUIRED_PDF_DISCUSSION_COLUMNS` (three independent literal copies of the
# same 5 columns -- flagged as a WARNING in that PR's verify report). Both
# `llm_validation.py` and `expert_alignment.py` now import the same list
# object from `pdf_discussion_pipeline.py` instead of redefining it, so a
# future schema edit can never silently desynchronize the xlsx producer
# (`assemble_discussion_xlsx`) from its consumers (this module's
# `validate_pdf_discussion_row`, `expert_alignment.py`'s xlsx reader). No
# circular import risk: `pdf_discussion_pipeline.py` has no import path back
# to either `llm_validation.py` or `expert_alignment.py`.
COLUMNAS_FINALES = _PDF_DISCUSSION_COLUMNAS_FINALES

_MESES = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "setiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12",
}


_ISO_FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_fecha(value: str | None) -> pd.Timestamp:
    if not value:
        return pd.NaT
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d{1,2})\s+de\s+([a-záéíóúñ]+)\s+de\s+(\d{4})", text)
    if match:
        day, month_name, year = match.groups()
        month = _MESES.get(month_name)
        if month:
            return pd.to_datetime(f"{year}-{month}-{int(day):02d}", errors="coerce")
    match = re.fullmatch(r"([a-záéíóúñ]+)\s+de\s+(\d{4})", text)
    if match:
        month_name, year = match.groups()
        month = _MESES.get(month_name)
        if month:
            return pd.to_datetime(f"{year}-{month}-01", errors="coerce")
    # Explicit, unambiguous ISO check BEFORE the dayfirst=True fallback below:
    # an already-ISO "YYYY-MM-DD" string must never go through dayfirst=True,
    # which silently swaps day/month whenever both are <=12 (e.g.
    # "2026-01-10" would otherwise become 2026-10-01).
    if _ISO_FECHA_RE.match(text):
        return pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    # Final fallback for genuinely ambiguous formats (e.g. slash-separated
    # DD/MM/YYYY, which Spanish-locale reports do write day-first).
    return pd.to_datetime(value, errors="coerce", dayfirst=True)


def _iso_fecha(value: str | pd.Timestamp) -> str | None:
    parsed = _parse_fecha(str(value)) if not isinstance(value, pd.Timestamp) else value
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _overlaps(start: str, end: str, user_start: str, user_end: str) -> bool:
    start_ts = _parse_fecha(start)
    end_ts = _parse_fecha(end)
    user_start_ts = _parse_fecha(user_start)
    user_end_ts = _parse_fecha(user_end)
    if any(pd.isna(x) for x in [start_ts, end_ts, user_start_ts, user_end_ts]):
        return False
    return start_ts <= user_end_ts and end_ts >= user_start_ts


def validate_pdf_discussion_row(
    response_text: str,
    *,
    circuito_pdf: str,
    fecha_inicio_usuario: str,
    fecha_fin_usuario: str,
) -> dict[str, Any]:
    """Validate a candidate PDF-fragment classification response.

    First, if `circuito_pdf` is `None`/empty/whitespace-only, the fragment is
    rejected outright before parsing `response_text` at all — this reinstates
    the original notebook driver loop's gate on `circuito_pdf`, which the
    move of the `Circuito`-forcing step into this function otherwise dropped.

    Otherwise, parses `response_text` as JSON (reusing `parse_llm_json`, same
    as `validate_auto_simulator_response` above). A parsed object whose
    `include` key is not `True` is a normal "exclude this fragment" outcome
    (`ok: False`, `data: None`, the model's own `reason` as the single
    error), not a malformed response. Otherwise, `Circuito` is force-set to
    `circuito_pdf` (never trusting the LLM's own value — a
    security/correctness invariant carried over unmodified from the
    notebook), then the required non-empty `COLUMNAS_FINALES` columns (an
    explicit JSON `null` counts as empty, not the literal string `"None"`),
    date parseability, start<=end ordering, and overlap with
    `fecha_inicio_usuario`/`fecha_fin_usuario` are checked. On success,
    returns a `data` dict with exactly `COLUMNAS_FINALES` keys, with
    `Fecha inicio`/`Fecha fin` normalized to ISO form.
    """
    if circuito_pdf is None or not str(circuito_pdf).strip():
        return {"ok": False, "data": None, "errors": ["circuito_pdf no puede ser None ni vacío"]}

    try:
        parsed = parse_llm_json(response_text or "")
    except Exception as exc:  # noqa: BLE001 - mirrors validate_auto_simulator_response's broad catch
        return {"ok": False, "data": None, "errors": [f"JSON inválido: {exc}"]}
    if not isinstance(parsed, dict):
        return {"ok": False, "data": None, "errors": ["La respuesta debe ser un objeto JSON."]}

    if parsed.get("include") is not True:
        return {"ok": False, "data": None, "errors": [str(parsed.get("reason", "include=false"))]}

    parsed["Circuito"] = circuito_pdf

    errors: list[str] = []
    for col in COLUMNAS_FINALES:
        value = parsed.get(col)
        if value is None or not str(value).strip():
            errors.append(f"{col} vacio")

    start = _iso_fecha(parsed.get("Fecha inicio"))
    end = _iso_fecha(parsed.get("Fecha fin"))
    if start is None:
        errors.append("Fecha inicio invalida")
    if end is None:
        errors.append("Fecha fin invalida")
    if start and end and _parse_fecha(start) > _parse_fecha(end):
        errors.append("Fecha inicio posterior a Fecha fin")
    if start and end and not _overlaps(start, end, fecha_inicio_usuario, fecha_fin_usuario):
        errors.append("La discusion no se traslapa con el rango del usuario")

    if errors:
        return {"ok": False, "data": None, "errors": errors}

    data = {col: str(parsed[col]).strip() for col in COLUMNAS_FINALES}
    data["Fecha inicio"] = start
    data["Fecha fin"] = end
    return {"ok": True, "data": data, "errors": []}
