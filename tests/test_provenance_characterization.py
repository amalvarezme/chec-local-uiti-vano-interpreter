"""Characterization tests pinning the CURRENT behavior of the two existing
provenance validators before they are migrated onto a shared generic core
(`sdd/report-command-pipeline`, Phase 1).

These tests assert the FULL `errors` list (not just substring membership)
so that a byte-identical refactor can be verified mechanically: run this
file before extracting the generic core (must pass against the frozen
implementation) and again immediately after (must still pass, unchanged).

Distinct from `tests/test_llm_validation.py` / `tests/test_provenance.py`,
which exercise functional correctness with looser ("any(... in error)")
assertions and are expected to keep passing independently of this file.
"""

from __future__ import annotations

import copy

from chec_local_interpreter.expert_alignment import (
    EXPERT_ALIGNMENT_AGENT_ID,
    validar_provenance_expert_alignment,
)
from chec_local_interpreter.llm_validation import (
    BASE_AGENT_ID,
    validar_provenance_base,
)

# --- Fixtures: validar_provenance_base ---------------------------------


def _base_domain_context() -> dict:
    return {
        "variable_groups": {
            "Entorno/Riesgo": {"variables": ["NR_T", "DDT"]},
            "Evento/Impacto": {"variables": ["UITI_VANO", "CNT_TRF"]},
        }
    }


def _base_context(unavailable: list[str] | None = None) -> dict:
    return {
        "daily_series": [{"fecha_dia": "2026-01-01"}, {"fecha_dia": "2026-01-02"}],
        "critical_points": [{"fecha_dia": "2026-01-02", "critical_point_id": "cp-2026-01-02"}],
        "critical_periods": [
            {
                "critical_period_id": "period-2026-01-01-2026-01-02",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            }
        ],
        "metadata": {"unavailable_optional_columns": unavailable or []},
        "domain": _base_domain_context(),
    }


def _base_finding(data_ref: list[str], *, rule: str = "03_uiti_vano_behavior_explainer", agent: str | None = None) -> dict:
    return {
        "title": "Punto dominante",
        "text": "El punto concentra el comportamiento del periodo.",
        "evidence": [],
        "referenced_events": [],
        "variable_groups_used": [],
        "confidence": "media",
        "provenance": {
            "data_ref": data_ref,
            "agent": agent or BASE_AGENT_ID,
            "rule": rule,
        },
    }


# --- Characterization: validar_provenance_base --------------------------


def test_char_base_absent_provenance_passes():
    context = _base_context()
    data = {"key_findings": [{"title": "t", "text": "x"}]}
    result = validar_provenance_base(data, context)
    assert result == {"ok": True, "errors": []}


def test_char_base_currently_passing_case():
    context = _base_context()
    data = {"key_findings": [_base_finding(["2026-01-02", "cp-2026-01-02", "UITI_VANO"])]}
    result = validar_provenance_base(data, context)
    assert result == {"ok": True, "errors": []}


def test_char_base_malformed_provenance_not_a_dict():
    context = _base_context()
    data = {"key_findings": [{"title": "t", "text": "x", "provenance": "not-a-dict"}]}
    result = validar_provenance_base(data, context)
    assert result == {"ok": False, "errors": ["key_findings: provenance must be an object."]}


def test_char_base_bad_agent():
    context = _base_context()
    data = {"key_findings": [_base_finding(["UITI_VANO"], agent="expert-alignment")]}
    result = validar_provenance_base(data, context)
    assert result == {
        "ok": False,
        "errors": ["key_findings: provenance.agent must be 'historical', got: 'expert-alignment'"],
    }


def test_char_base_bad_rule():
    context = _base_context()
    data = {"key_findings": [_base_finding(["UITI_VANO"], rule="not-a-real-rule")]}
    result = validar_provenance_base(data, context)
    assert result == {
        "ok": False,
        "errors": ["key_findings: provenance.rule not in the allowed rule list: 'not-a-real-rule'"],
    }


def test_char_base_unresolvable_date():
    context = _base_context()
    data = {"key_findings": [_base_finding(["2099-12-31"])]}
    result = validar_provenance_base(data, context)
    assert result == {
        "ok": False,
        "errors": ["key_findings: provenance.data_ref cites a date outside the allowed context: 2099-12-31"],
    }


def test_char_base_unresolvable_critical_point_id():
    context = _base_context()
    data = {"key_findings": [_base_finding(["cp-2099-12-31"])]}
    result = validar_provenance_base(data, context)
    assert result == {
        "ok": False,
        "errors": ["key_findings: provenance.data_ref cites an unknown critical_point_id: cp-2099-12-31"],
    }


def test_char_base_unavailable_variable():
    context = _base_context(["NR_T"])
    data = {"key_findings": [_base_finding(["NR_T"])]}
    result = validar_provenance_base(data, context)
    assert result == {
        "ok": False,
        "errors": ["key_findings: provenance.data_ref cites an unknown or unavailable variable: 'NR_T'"],
    }


def test_char_base_unknown_variable_outside_universe():
    context = _base_context()
    data = {"key_findings": [_base_finding(["NOT_A_REAL_VARIABLE"])]}
    result = validar_provenance_base(data, context)
    assert result == {
        "ok": False,
        "errors": [
            "key_findings: provenance.data_ref cites an unknown or unavailable variable: 'NOT_A_REAL_VARIABLE'"
        ],
    }


def test_char_base_empty_data_ref_list():
    context = _base_context()
    data = {"key_findings": [_base_finding([])]}
    result = validar_provenance_base(data, context)
    assert result == {
        "ok": False,
        "errors": ["key_findings: provenance.data_ref must be a non-empty list."],
    }


def test_char_base_is_side_effect_free():
    context = _base_context()
    data = {"key_findings": [_base_finding(["UITI_VANO"])]}
    snapshot = copy.deepcopy(data)
    validar_provenance_base(data, context)
    assert data == snapshot


# --- Fixtures: validar_provenance_expert_alignment -----------------------


def _ea_context(predictive: list[str] | None = None) -> dict:
    return {
        "periodo_informe": {"inicio": "2026-01-01", "fin": "2026-01-31"},
        "fechas_informe": [
            {"source": "critical_point", "fecha_inicio": "2026-01-10", "fecha_fin": "2026-01-10"}
        ],
        "llm1_analysis": {},
        "llm2_inference_analysis": {},
        "variables_modelo_predictivo": predictive if predictive is not None else ["CNT_TRF"],
        "pdf_expert_matches": [
            {
                "Circuito": "DON23L13",
                "Fecha inicio": "2026-01-09",
                "Fecha fin": "2026-01-11",
                "Análisis": "UITI_VANO alto",
                "Evidencia": "Evidencia experta verificable",
                "pdf_row_index": 3,
            }
        ],
    }


def _ea_item(data_ref: list[str], *, rule: str = "02_predictive_variable_prioritization", agent: str | None = None) -> dict:
    return {
        "tema": "UITI_VANO alto",
        "fuentes": ["Agente predictivo"],
        "explicacion": "Coinciden temporalmente.",
        "provenance": {
            "data_ref": data_ref,
            "agent": agent or EXPERT_ALIGNMENT_AGENT_ID,
            "rule": rule,
        },
    }


def _ea_data(*, coincidencias: list | None = None, diferencias: list | None = None, variables: list | None = None) -> dict:
    return {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}},
        "coincidencias": coincidencias or [],
        "diferencias": diferencias or [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": variables or [],
        "sintesis_final": "La comparación es consistente y requiere validación operacional.",
    }


# --- Characterization: validar_provenance_expert_alignment ---------------


def test_char_ea_absent_provenance_passes():
    context = _ea_context()
    result = validar_provenance_expert_alignment(_ea_data(), context)
    assert result == {"ok": True, "errors": []}


def test_char_ea_currently_passing_case():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item(["2026-01-10", "CNT_TRF", "pdf_row_index:3"])])
    result = validar_provenance_expert_alignment(data, context)
    assert result == {"ok": True, "errors": []}


def test_char_ea_malformed_provenance_not_a_dict():
    context = _ea_context()
    data = _ea_data(
        coincidencias=[
            {"tema": "x", "fuentes": ["a"], "explicacion": "e", "provenance": "not-a-dict"}
        ]
    )
    result = validar_provenance_expert_alignment(data, context)
    assert result == {"ok": False, "errors": ["coincidencias: provenance debe ser un objeto."]}


def test_char_ea_bad_agent():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item(["CNT_TRF"], agent="some-other-agent")])
    result = validar_provenance_expert_alignment(data, context)
    assert result == {
        "ok": False,
        "errors": [
            "coincidencias: provenance.agent debe ser 'expert-alignment', valor recibido: 'some-other-agent'"
        ],
    }


def test_char_ea_bad_rule():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item(["CNT_TRF"], rule="not-a-real-rule")])
    result = validar_provenance_expert_alignment(data, context)
    assert result == {
        "ok": False,
        "errors": ["coincidencias: provenance.rule no está en la lista de reglas permitidas: 'not-a-real-rule'"],
    }


def test_char_ea_unresolvable_date():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item(["2099-12-31"])])
    result = validar_provenance_expert_alignment(data, context)
    assert result == {
        "ok": False,
        "errors": ["coincidencias: provenance.data_ref cites a date outside the allowed context: 2099-12-31"],
    }


def test_char_ea_unresolvable_variable():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item(["NOT_REAL_VAR"])])
    result = validar_provenance_expert_alignment(data, context)
    assert result == {
        "ok": False,
        "errors": ["coincidencias: provenance.data_ref cites an unknown variable: 'NOT_REAL_VAR'"],
    }


def test_char_ea_unresolvable_pdf_row_index():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item(["pdf_row_index:99"])])
    result = validar_provenance_expert_alignment(data, context)
    assert result == {
        "ok": False,
        "errors": ["coincidencias: provenance.data_ref cites an unknown pdf_row_index: pdf_row_index:99"],
    }


def test_char_ea_empty_data_ref_list():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item([])])
    result = validar_provenance_expert_alignment(data, context)
    assert result == {
        "ok": False,
        "errors": ["coincidencias: provenance.data_ref debe ser una lista no vacía."],
    }


def test_char_ea_known_failing_fixture_multiple_errors_across_sections():
    """Known-failing fixture (task 1.2): two independent violations across two
    different provenance sections in a single call, pinning both the exact
    error text AND the accumulation order (section iteration order,
    `coincidencias` before `variables_a_priorizar`)."""
    context = _ea_context()
    data = _ea_data(
        coincidencias=[_ea_item(["2099-12-31"], rule="not-a-real-rule")],
        variables=[_ea_item(["CNT_TRF"], agent="bad-agent")],
    )
    result = validar_provenance_expert_alignment(data, context)
    assert result == {
        "ok": False,
        "errors": [
            "coincidencias: provenance.rule no está en la lista de reglas permitidas: 'not-a-real-rule'",
            "coincidencias: provenance.data_ref cites a date outside the allowed context: 2099-12-31",
            "variables_a_priorizar: provenance.agent debe ser 'expert-alignment', valor recibido: 'bad-agent'",
        ],
    }


def test_char_ea_is_side_effect_free():
    context = _ea_context()
    data = _ea_data(coincidencias=[_ea_item(["CNT_TRF", "pdf_row_index:3"])])
    snapshot = copy.deepcopy(data)
    validar_provenance_expert_alignment(data, context)
    assert data == snapshot
