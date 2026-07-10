from __future__ import annotations

import json

from chec_local_interpreter.llm_contracts import PROMPT_VERSION, load_output_schema, render_prompt
from chec_local_interpreter.llm_prompt import render_base_repair_prompt, render_compact_base_repair_prompt


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


def test_compact_base_repair_prompt_uses_skill_and_minimal_context():
    context = {
        "metadata": {"start": "2026-01-01", "end": "2026-01-31"},
        "selected_context": {"circuitos": ["C1"]},
        "summary": {"events": 3},
        "critical_points": [
            {
                "critical_point_id": "cp-2026-01-02",
                "fecha_dia": "2026-01-02",
                "metrics": {"UITI_VANO": 10},
                "selection_reason": "pico",
                "top_rows": [{"FID_VANO": "A"}, {"FID_VANO": "B"}, {"FID_VANO": "C"}, {"FID_VANO": "D"}],
            }
        ],
        "domain": {"variable_groups": {"Evento/Impacto": ["UITI_VANO"]}, "relationship_rules": list(range(20))},
    }
    prompt = render_compact_base_repair_prompt(
        context,
        prompt_version=PROMPT_VERSION,
        top_vanos_percentile=97,
        max_critical_points=1,
    )
    assert "Reparación Base" in prompt
    assert PROMPT_VERSION in prompt
    assert '"C1"' in prompt
    assert '"FID_VANO": "D"' not in prompt
    assert "máximo 5 ítems" in prompt
    assert "{{CONTEXT_JSON}}" not in prompt

    prompt_alias = render_compact_base_repair_prompt(
        context,
        prompt_version=PROMPT_VERSION,
        top_vanos_percentile=97,
        max_critical_points=1,
    )
    prompt_new = render_base_repair_prompt(
        context,
        prompt_version=PROMPT_VERSION,
        top_vanos_percentile=97,
        max_critical_points=1,
    )
    assert prompt_alias == prompt_new


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
        "02_critical_point_interpreter",
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
