from __future__ import annotations

import json

from chec_local_interpreter.llm_contracts import PROMPT_VERSION, load_output_schema, render_prompt


def test_prompt_rendering_includes_context_schema_and_version():
    context = {"selected_context": {"circuitos": ["C1"]}, "critical_points": []}
    schema = load_output_schema()
    prompt = render_prompt(
        context_json=json.dumps(context),
        output_schema_json=json.dumps(schema),
    )
    assert '"C1"' in prompt
    assert "uiti_vano_explanation.output_schema.v1" in prompt
    assert PROMPT_VERSION in prompt
    assert "Contrato de Salida Base" in prompt


# --- Phase 6.3: additive optional `provenance` property on key_findings ----


def test_output_schema_declares_optional_per_finding_provenance():
    schema = load_output_schema()
    assert schema["$id"] == "uiti_vano_explanation.output_schema.v1"

    finding_schema = schema["properties"]["key_findings"]["items"]
    assert "provenance" in finding_schema["properties"]
    assert "provenance" not in finding_schema["required"], (
        "provenance must be optional per key_finding, not required — backward compatible"
    )

    provenance_schema = finding_schema["properties"]["provenance"]
    assert provenance_schema["additionalProperties"] is False
    assert set(provenance_schema["required"]) == {"data_ref", "agent", "rule"}
    assert provenance_schema["properties"]["agent"]["const"] == "historical"
    assert provenance_schema["properties"]["data_ref"]["type"] == "array"
    assert provenance_schema["properties"]["data_ref"]["minItems"] == 1
    assert set(provenance_schema["properties"]["rule"]["enum"]) == {
        "01_structured_context_builder",
        "02_window_interpreter",
        "03_uiti_vano_behavior_explainer",
        "04_domain_grounding_guardrails",
        "05_llm_output_validator",
        "06_base_repair",
        "07_base_output_contract",
    }


def test_prompt_snapshot_includes_optional_provenance_property():
    context = {"selected_context": {"circuitos": ["C1"]}, "critical_points": []}
    schema = load_output_schema()
    prompt = render_prompt(
        context_json=json.dumps(context),
        output_schema_json=json.dumps(schema),
    )
    assert '"provenance"' in prompt
