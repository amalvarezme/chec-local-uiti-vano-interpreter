from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised only in minimal environments
    Draft202012Validator = None

from chec_local_interpreter.llm_contracts import load_output_schema

FORBIDDEN_TERMS = (
    "rag",
    "bitacora",
    "bitácora",
    "normativa",
    "modelo predictivo",
    "predice",
    "mascara",
    "máscara",
    "what-if",
    "what if",
    "simulacion",
    "simulación",
    "reporte final",
    "causó definitivamente",
    "causo definitivamente",
    "demuestra que",
    "la causa fue",
)


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
    return json.loads(text)


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
    return dates


def _critical_point_ids(context: dict[str, Any]) -> set[str]:
    return {
        str(item.get("critical_point_id"))
        for item in context.get("critical_points", [])
        if isinstance(item, dict) and item.get("critical_point_id")
    }


def _unavailable_columns(context: dict[str, Any]) -> set[str]:
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    return {str(column).upper() for column in metadata.get("unavailable_optional_columns", [])}


def _guardrail_errors(data: dict[str, Any], context: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    
    # Exclude 'limitations' and 'data_gaps' from the forbidden term check.
    # The LLM often correctly denies capabilities (e.g. "no simulation is done") here.
    filtered_data = {k: v for k, v in data.items() if k not in ("limitations", "data_gaps")}
    text_blob = "\n".join(_flatten_strings(filtered_data)).lower()
    
    for term in FORBIDDEN_TERMS:
        if term.lower() in text_blob:
            errors.append(f"Forbidden term or claim found: {term}")

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

    if not data.get("limitations"):
        errors.append("Output must include limitations.")
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


def save_invalid_output(response_text: str, errors: list[str], output_dir: str | Path, timestamp: str) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    raw_path = directory / f"invalid_llm_output_{timestamp}.txt"
    errors_path = directory / f"llm_validation_errors_{timestamp}.json"
    raw_path.write_text(response_text, encoding="utf-8")
    errors_path.write_text(json.dumps({"errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_path, errors_path
