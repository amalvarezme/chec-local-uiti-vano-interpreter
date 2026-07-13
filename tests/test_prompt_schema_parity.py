"""Regression guard: the human-readable contract playbooks must never drift
from the machine-enforced JSON schemas.

Design (SDD `reporte-perf-optimization`, item 1b): the historical/inference
output schemas are the enforced contract, but the first-attempt prompt
playbooks that tell the LLM what to produce did not enumerate every
schema-`required` top-level key -- `period_synthesis` (historical) and
`limitaciones` (inference) were each missing from their playbook's
required-keys enumeration, even though the schema and the validator both
require them. This test asserts every schema-required key is verbatim
present inside a dedicated "Claves requeridas" enumeration section of the
matching playbook, so a future schema change that isn't mirrored in the
playbook fails loudly here instead of silently degrading first-attempt LLM
output quality.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from chec_local_interpreter.inference_validation import validar_respuesta_inferencia_strict
from chec_local_interpreter.llm_validation import validate_llm_response

from tests.test_agent_tools_historical import (
    _sample_context as _historical_sample_context,
    _valid_output_with_provenance as _historical_valid_output,
)
from tests.test_agent_tools_historical import build_context as _historical_build_context
from tests.test_agent_tools_inference import (
    _sample_context as _inference_sample_context,
    _valid_output_with_provenance as _inference_valid_output,
)
from tests.test_agent_tools_inference import build_context as _inference_build_context

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_SCHEMA_PATH = (
    PROJECT_ROOT / "src" / "chec_local_interpreter" / "prompt_assets" / "uiti_vano_explanation.output_schema.json"
)
INFERENCE_SCHEMA_PATH = PROJECT_ROOT / "src" / "chec_local_interpreter" / "prompt_assets" / "inference.output_schema.json"
HISTORICAL_PLAYBOOK_PATH = PROJECT_ROOT / ".claude" / "skills" / "historical" / "prompt" / "07_base_output_contract.md"
INFERENCE_PLAYBOOK_PATH = PROJECT_ROOT / ".claude" / "skills" / "inference" / "prompt" / "05_llm_output_validator.md"

REQUIRED_KEYS_SECTION_RE = re.compile(
    r"^#+\s*Claves [Rr]equeridas\s*$(?P<body>.*?)(?=^#+\s|\Z)",
    re.MULTILINE | re.DOTALL,
)


def _required_keys_section(markdown_text: str) -> str:
    match = REQUIRED_KEYS_SECTION_RE.search(markdown_text)
    assert match is not None, "playbook must have a 'Claves requeridas' enumeration section"
    return match.group("body")


def _assert_all_required_keys_enumerated(schema_path: Path, playbook_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required_keys = schema["required"]
    section = _required_keys_section(playbook_path.read_text(encoding="utf-8"))

    missing = [key for key in required_keys if f"`{key}`" not in section]
    assert not missing, f"{playbook_path.name} 'Claves requeridas' section is missing: {missing}"


def test_historical_playbook_enumerates_all_schema_required_keys():
    _assert_all_required_keys_enumerated(HISTORICAL_SCHEMA_PATH, HISTORICAL_PLAYBOOK_PATH)


def test_inference_playbook_enumerates_all_schema_required_keys():
    _assert_all_required_keys_enumerated(INFERENCE_SCHEMA_PATH, INFERENCE_PLAYBOOK_PATH)


def test_corrected_historical_payload_with_period_synthesis_validates():
    context = _historical_sample_context()
    envelope = _historical_build_context(context)
    response = _historical_valid_output(envelope["context"])

    assert "period_synthesis" in response
    result = validate_llm_response(json.dumps(response, ensure_ascii=False), envelope["context"])
    assert result.ok, result.errors


def test_corrected_inference_payload_with_limitaciones_validates():
    context = _inference_sample_context()
    envelope = _inference_build_context(context)
    response = _inference_valid_output(envelope["context"])

    assert "limitaciones" in response
    result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), envelope["context"])
    assert result["ok"], result["errors"]
