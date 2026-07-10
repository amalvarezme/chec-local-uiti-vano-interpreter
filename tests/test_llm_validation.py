from __future__ import annotations

import copy
import json

from chec_local_interpreter.llm_contracts import PROMPT_VERSION, load_output_schema
from chec_local_interpreter.llm_validation import (
    BASE_AGENT_ID,
    BASE_PROVENANCE_RULES,
    allowed_critical_point_ids,
    allowed_dates,
    unavailable_columns,
    validar_provenance_base,
    validate_llm_response,
)


def _context(unavailable: list[str] | None = None) -> dict:
    return {
        "metadata": {"unavailable_optional_columns": unavailable or []},
        "daily_series": [{"fecha_dia": "2026-01-01"}, {"fecha_dia": "2026-01-02"}],
        "critical_points": [
            {
                "critical_point_id": "cp-2026-01-02",
                "fecha_dia": "2026-01-02",
                "metrics": {"UITI_VANO": 10.0},
                "selection_reason": "Punto critico entregado por codigo.",
            }
        ],
        "critical_periods": [
            {
                "critical_period_id": "period-2026-01-01-2026-01-02",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "summary": "Periodo critico entregado por codigo.",
            }
        ],
    }


def _valid_output() -> dict:
    return {
        "source": "llm",
        "prompt_version": PROMPT_VERSION,
        "headline": "Concentracion de UITI_VANO",
        "section_title": "Hallazgos del periodo",
        "executive_summary": ["La evidencia tabular muestra un punto dominante."],
        "key_findings": [
            {
                "title": "Punto dominante",
                "text": "El punto cp-2026-01-02 concentra el comportamiento del periodo.",
                "evidence": [
                    {
                        "date": "2026-01-02",
                        "critical_point_id": "cp-2026-01-02",
                        "variable": "UITI_VANO",
                        "summary": "Punto critico entregado por codigo.",
                    }
                ],
                "referenced_events": [
                    {
                        "date": "2026-01-02",
                        "critical_point_id": "cp-2026-01-02",
                        "indicator_value": 10.0,
                        "selection_reason": "Punto critico entregado por codigo.",
                    }
                ],
                "variable_groups_used": ["Evento/Impacto"],
                "confidence": "media",
            }
        ],
        "circuit_characterization": {
            "text": "Characterization text.",
            "p97_vanos_uiti_vano": ["V1"],
            "p97_vanos_eventos": ["V2"],
            "top_3_modes_related": ["Mode1"],
            "probable_justifications_rules": ["Rule1"]
        },
        "period_synthesis": "El comportamiento del periodo se concentra en el punto critico entregado.",
        "data_gaps": [],
        "limitations": ["Solo se usa la informacion estructurada disponible."],
        "recommended_actions": ["Revisar los eventos fuente del punto critico."],
    }


def test_valid_json_passes():
    result = validate_llm_response(json.dumps(_valid_output()), _context(), load_output_schema())
    assert result.ok


def test_echoed_schema_meta_keys_are_stripped():
    # Weaker models copy the schema's $schema/$id metadata into their answer; under
    # additionalProperties:false that used to invalidate an otherwise-correct output.
    output = _valid_output()
    output = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "uiti_vano_explanation.output_schema.v1",
        **output,
    }
    result = validate_llm_response(json.dumps(output), _context(), load_output_schema())
    assert result.ok, result.errors
    assert "$schema" not in result.data
    assert "$id" not in result.data


def test_malformed_json_fails():
    result = validate_llm_response("{bad json", _context(), load_output_schema())
    assert not result.ok
    assert "Invalid JSON" in result.errors[0]


def test_date_outside_context_fails():
    output = _valid_output()
    output["key_findings"][0]["evidence"][0]["date"] = "2026-01-09"
    result = validate_llm_response(json.dumps(output), _context(), load_output_schema())
    assert not result.ok
    assert any("Referenced date outside context" in error for error in result.errors)


def test_critical_period_id_from_context_passes():
    output = _valid_output()
    output["key_findings"][0]["evidence"][0]["date"] = "2026-01-01"
    output["key_findings"][0]["evidence"][0]["critical_point_id"] = "period-2026-01-01-2026-01-02"
    output["key_findings"][0]["referenced_events"][0]["date"] = "2026-01-02"
    output["key_findings"][0]["referenced_events"][0]["critical_point_id"] = "period-2026-01-01-2026-01-02"
    result = validate_llm_response(json.dumps(output), _context(), load_output_schema())
    assert result.ok, result.errors


def test_unknown_critical_period_id_fails():
    output = _valid_output()
    output["key_findings"][0]["evidence"][0]["critical_point_id"] = "period-2026-02-01-2026-02-02"
    result = validate_llm_response(json.dumps(output), _context(), load_output_schema())
    assert not result.ok
    assert any("Referenced critical_point_id outside context" in error for error in result.errors)


def test_unavailable_column_referenced_as_present_fails():
    output = _valid_output()
    output["period_synthesis"] = "NR_T muestra estres ambiental disponible en los datos."
    output["data_gaps"] = ["No todas las variables opcionales estan disponibles."]
    result = validate_llm_response(json.dumps(output), _context(["NR_T"]), load_output_schema())
    assert not result.ok
    assert any("Unavailable column" in error for error in result.errors)


# --- Phase 6: public context accessors + validar_provenance_base -----------


def _domain_context() -> dict:
    return {
        "variable_groups": {
            "Entorno/Riesgo": {"variables": ["NR_T", "DDT"]},
            "Evento/Impacto": {"variables": ["UITI_VANO", "CNT_TRF"]},
        }
    }


def _base_context(unavailable: list[str] | None = None) -> dict:
    context = _context(unavailable)
    context["domain"] = _domain_context()
    return context


def _finding_with_provenance(data_ref: list[str]) -> dict:
    return {
        "title": "Punto dominante",
        "text": "El punto concentra el comportamiento del periodo.",
        "evidence": [
            {
                "date": "2026-01-02",
                "critical_point_id": "cp-2026-01-02",
                "variable": "UITI_VANO",
                "summary": "Punto critico entregado por codigo.",
            }
        ],
        "referenced_events": [],
        "variable_groups_used": ["Evento/Impacto"],
        "confidence": "media",
        "provenance": {
            "data_ref": data_ref,
            "agent": BASE_AGENT_ID,
            "rule": "03_uiti_vano_behavior_explainer",
        },
    }


def test_public_context_accessors_exist_and_match_internal_helpers():
    context = _base_context()
    assert allowed_dates(context) == {"2026-01-01", "2026-01-02"}
    assert allowed_critical_point_ids(context) == {"cp-2026-01-02", "period-2026-01-01-2026-01-02"}
    assert unavailable_columns(context) == set()
    assert unavailable_columns(_base_context(["NR_T"])) == {"NR_T"}


def test_base_agent_id_and_provenance_rules_are_hermetic():
    assert BASE_AGENT_ID == "historical"
    assert BASE_PROVENANCE_RULES == {
        "01_structured_context_builder",
        "02_critical_point_interpreter",
        "03_uiti_vano_behavior_explainer",
        "04_domain_grounding_guardrails",
        "05_llm_output_validator",
        "06_base_repair",
        "07_base_output_contract",
    }


def test_validar_provenance_base_passes_when_absent():
    """Backward compatible: a key_finding without a provenance key is never flagged."""
    context = _base_context()
    data = {"key_findings": [{"title": "t", "text": "x"}]}
    result = validar_provenance_base(data, context)
    assert result["ok"], result["errors"]
    assert result["errors"] == []


def test_validar_provenance_base_passes_when_every_data_ref_resolves():
    context = _base_context()
    data = {"key_findings": [_finding_with_provenance(["2026-01-02", "cp-2026-01-02", "UITI_VANO"])]}
    result = validar_provenance_base(data, context)
    assert result["ok"], result["errors"]


def test_validar_provenance_base_fails_closed_on_unresolvable_date():
    context = _base_context()
    data = {"key_findings": [_finding_with_provenance(["2099-12-31"])]}
    result = validar_provenance_base(data, context)
    assert not result["ok"]
    assert any("2099-12-31" in error for error in result["errors"])


def test_validar_provenance_base_fails_closed_on_unresolvable_critical_point_id():
    context = _base_context()
    data = {"key_findings": [_finding_with_provenance(["cp-2099-12-31"])]}
    result = validar_provenance_base(data, context)
    assert not result["ok"]
    assert any("cp-2099-12-31" in error for error in result["errors"])


def test_validar_provenance_base_fails_closed_on_unavailable_variable():
    context = _base_context(["NR_T"])
    data = {"key_findings": [_finding_with_provenance(["NR_T"])]}
    result = validar_provenance_base(data, context)
    assert not result["ok"]
    assert any("NR_T" in error for error in result["errors"])


def test_validar_provenance_base_fails_closed_on_unknown_variable():
    context = _base_context()
    data = {"key_findings": [_finding_with_provenance(["NOT_A_REAL_VARIABLE"])]}
    result = validar_provenance_base(data, context)
    assert not result["ok"]
    assert any("NOT_A_REAL_VARIABLE" in error for error in result["errors"])


def test_validar_provenance_base_fails_when_agent_does_not_match():
    context = _base_context()
    finding = _finding_with_provenance(["UITI_VANO"])
    finding["provenance"]["agent"] = "expert-alignment"
    data = {"key_findings": [finding]}
    result = validar_provenance_base(data, context)
    assert not result["ok"]
    assert any("agent" in error.lower() for error in result["errors"])


def test_validar_provenance_base_fails_when_rule_not_in_allow_list():
    context = _base_context()
    finding = _finding_with_provenance(["UITI_VANO"])
    finding["provenance"]["rule"] = "not-a-real-rule"
    data = {"key_findings": [finding]}
    result = validar_provenance_base(data, context)
    assert not result["ok"]
    assert any("rule" in error.lower() for error in result["errors"])


def test_validar_provenance_base_is_side_effect_free():
    context = _base_context()
    data = {"key_findings": [_finding_with_provenance(["UITI_VANO"])]}
    snapshot = copy.deepcopy(data)
    validar_provenance_base(data, context)
    assert data == snapshot
