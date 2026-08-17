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


# --- Los tres campos del percentil que el esquema rechazaba -------------------


def test_el_esquema_admite_los_tres_campos_del_percentil_que_el_informe_si_lee():
    """`additionalProperties: false` los rechazaba, y tres consumidores los leen.

    El Skill del rol `historical` pide copiarlos del contexto
    (`top_vanos_percentile`, `p97_vanos_uiti_vano`, `p97_vanos_eventos`), pero
    `circuit_characterization` declara `additionalProperties: false` y no los tenia
    entre sus propiedades: un agente que siguiera el Skill al pie de la letra fallaba
    la validacion y gastaba reintentos, y el que se salvaba era el que se saltaba esa
    linea.

    Lo que se pierde no es cosmetico. `expert_alignment` los pasa al contexto de
    alineacion y `vault_note_contract._render_characterization` imprime con ellos
    "Percentil 97 por UITI_VANO" y "Percentil 97 por eventos". Medido: CERO notas de
    boveda del repositorio contienen esas dos lineas -- codigo muerto por un esquema
    que bloqueaba su unica fuente.

    Van OPCIONALES y no obligatorios: un contexto sin percentil configurado es un
    caso real, y exigirlos convertiria eso en un fallo de validacion.
    """
    schema = load_output_schema()
    caracterizacion = schema["properties"]["circuit_characterization"]

    for campo in ("top_vanos_percentile", "p97_vanos_uiti_vano", "p97_vanos_eventos"):
        assert campo in caracterizacion["properties"], (
            f"{campo} sigue sin cabida: el Skill lo pide y el esquema lo rechaza"
        )
        assert campo not in caracterizacion["required"], (
            f"{campo} no puede ser obligatorio: un contexto sin percentil es real"
        )

    assert caracterizacion["additionalProperties"] is False, (
        "la puerta se abre para tres campos concretos, no para cualquiera"
    )
    assert caracterizacion["properties"]["p97_vanos_uiti_vano"]["type"] == "array"
    assert caracterizacion["properties"]["p97_vanos_eventos"]["type"] == "array"
