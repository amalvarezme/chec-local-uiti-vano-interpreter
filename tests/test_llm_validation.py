from __future__ import annotations

import json

from chec_local_interpreter.llm_contracts import PROMPT_VERSION, load_output_schema
from chec_local_interpreter.llm_validation import validate_llm_response


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


def test_malformed_json_fails():
    result = validate_llm_response("{bad json", _context(), load_output_schema())
    assert not result.ok
    assert "Invalid JSON" in result.errors[0]


def test_forbidden_scope_terms_fail():
    output = _valid_output()
    output["period_synthesis"] = "Segun RAG, el modelo predictivo explica el resultado."
    result = validate_llm_response(json.dumps(output), _context(), load_output_schema())
    assert not result.ok
    assert any("Forbidden" in error for error in result.errors)


def test_date_outside_context_fails():
    output = _valid_output()
    output["key_findings"][0]["evidence"][0]["date"] = "2026-01-09"
    result = validate_llm_response(json.dumps(output), _context(), load_output_schema())
    assert not result.ok
    assert any("Referenced date outside context" in error for error in result.errors)


def test_unavailable_column_referenced_as_present_fails():
    output = _valid_output()
    output["period_synthesis"] = "NR_T muestra estres ambiental disponible en los datos."
    output["data_gaps"] = ["No todas las variables opcionales estan disponibles."]
    result = validate_llm_response(json.dumps(output), _context(["NR_T"]), load_output_schema())
    assert not result.ok
    assert any("Unavailable column" in error for error in result.errors)
