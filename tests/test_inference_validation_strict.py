from __future__ import annotations

import copy
import json

from chec_impacto.interpretability.circuit_analysis import validar_respuesta_inferencia
from chec_local_interpreter.inference_validation import (
    INFERENCE_AGENT_ID,
    INFERENCE_PROVENANCE_RULES,
    allowed_critical_point_ids,
    allowed_dates,
    allowed_scenario_names,
    allowed_variables,
    validar_provenance_inferencia,
    validar_respuesta_inferencia_strict,
)

_ESCENARIO_NOMBRE = "Top P97 por UITI_VANO — período completo"


def _context() -> dict:
    return {
        "circuito_interes": "DON23L13",
        "fecha_inicio": "2026-01-01",
        "fecha_fin": "2026-01-31",
        "fechas_interes": ["2026-01-10"],
        "top_n_vanos": 20,
        "top_vanos_percentile": None,
        "top_k_vars": 20,
        "filtro_uiti_max": None,
        "ventana_climatica_horas": 12,
        "modelo": "mgcecdl_clasificacion",
        "modelo_tipo": "mgcecdl_clasificacion",
        "n_eventos": 10,
        "n_vanos": 5,
        "n_features": 2,
        "features": ["NR_T", "DDT"],
        "graph_feature_order": ["NR_T", "DDT"],
        "estimated_graph_source": "reconstruccion_mgcecdl_rbf",
        "estimated_graph_rbf_sigma": 1.0,
        "graph_html_paths": [
            {
                "escenario": _ESCENARIO_NOMBRE,
                "path": "top_uiti_periodo.html",
                "fuente": "reconstruccion_mgcecdl_rbf",
                "pesos": "normalizados_0_1_por_maximo",
            }
        ],
        "escenarios": [
            {
                "nombre": _ESCENARIO_NOMBRE,
                "criterio": "UITI_VANO_PROM",
                "fechas_interes": [],
                "n_eventos": 10,
                "n_vanos_efectivo": 5,
                "top_k_vars": 20,
                "ventana_climatica_horas": 12,
                "top_variables": [{"nombre": "NR_T", "score_normalizado": 0.9}],
                "modos": [{"nombre": "Entorno, riesgo y clima", "score_normalizado": 0.5}],
                "tabla_top_vanos": [],
                "grafo": {
                    "path": "top_uiti_periodo.html",
                    "fuente": "reconstruccion_mgcecdl_rbf",
                    "pesos": "normalizados_0_1_por_maximo",
                },
            }
        ],
        "metadata": {
            "uiti_vano_es_objetivo": True,
            "features_no_incluyen_objetivo": True,
            "grafo_estimado_desde_reconstruccion": True,
        },
    }


def _valid_response(context: dict) -> dict:
    return {
        "contexto": {
            "circuito": context["circuito_interes"],
            "periodo": {"inicio": context["fecha_inicio"], "fin": context["fecha_fin"]},
            "modelo": context["modelo"],
        },
        "entregables": {
            "grafos_html": [
                {
                    "escenario": _ESCENARIO_NOMBRE,
                    "path": "top_uiti_periodo.html",
                    "fuente": "reconstruccion_mgcecdl_rbf",
                    "pesos": "normalizados_0_1_por_maximo",
                }
            ]
        },
        "escenarios": [
            {"nombre": _ESCENARIO_NOMBRE, "interpretacion": "El escenario muestra concentracion en NR_T."}
        ],
        "discusion_grafos": [
            {"seccion": "periodo_completo", "lectura": "NR_T se asocia con COD_CAUSA en el grafo experto."}
        ],
        "coherencia_grafo_modelo": [
            "NR_T es coherente con una hipotesis operativa de riesgo por vegetacion."
        ],
        "hallazgos": ["NR_T aparece como variable relevante en el periodo."],
        "limitaciones": ["Kernel SHAP explica comportamiento del modelo."],
        "inferencias_predictivas": [
            {
                "horizonte": "periodo analizado",
                "riesgo": "moderado",
                "justificacion_modelo": "El modelo sugiere asociacion con NR_T.",
            }
        ],
        "hipotesis_modelo_predictivo": {
            "periodo_completo": ["El modelo es consistente con riesgo por vegetacion."],
            "puntos_criticos": [],
        },
    }


def _valid_response_with_provenance(context: dict) -> dict:
    response = _valid_response(context)
    response["escenarios"][0]["provenance"] = {
        "data_ref": ["NR_T", "2026-01-10", _ESCENARIO_NOMBRE],
        "agent": "inference",
        "rule": "02_circuit_scenario_interpreter",
    }
    response["discusion_grafos"][0]["provenance"] = {
        "data_ref": ["cp-2026-01-10"],
        "agent": "inference",
        "rule": "04_graph_connectivity_guardrails",
    }
    return response


# --- Allowed-universe accessors ---


def test_allowed_dates_includes_top_level_and_scenario_fechas_interes():
    context = _context()
    context["escenarios"][0]["fechas_interes"] = ["2026-01-15"]
    dates = allowed_dates(context)
    assert "2026-01-10" in dates
    assert "2026-01-15" in dates
    assert "2026-01-01" in dates
    assert "2026-01-31" in dates


def test_allowed_critical_point_ids_derived_from_dates():
    context = _context()
    ids = allowed_critical_point_ids(context)
    assert "cp-2026-01-10" in ids


def test_allowed_variables_from_features():
    context = _context()
    assert allowed_variables(context) == {"NR_T", "DDT"}


def test_allowed_scenario_names_from_context():
    context = _context()
    assert allowed_scenario_names(context) == {_ESCENARIO_NOMBRE}


# --- Schema + guardrail validator ---


def test_valid_response_passes_schema_and_guardrails():
    context = _context()
    response = _valid_response(context)

    result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)

    assert result["ok"], result["errors"]
    assert result["data"] is not None


def test_schema_invalid_missing_required_key_fails():
    context = _context()
    response = _valid_response(context)
    del response["limitaciones"]

    result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)

    assert not result["ok"]
    assert result["errors"]


def test_schema_allows_empty_escenarios_r1_r3_gap_shape():
    """`escenarios.minItems` is 0 (task 1.3): an empty `escenarios` array is a
    VALID terminal state (R1/R3 gap shapes, obs#219), not a schema violation.
    A context with zero scenarios has an empty allowed-scenario-names set, so
    this response can never fabricate one either."""
    context = _context()
    context["escenarios"] = []
    context["graph_html_paths"] = []
    response = _valid_response(context)
    response["escenarios"] = []
    response["entregables"]["grafos_html"] = []
    response["discusion_grafos"] = []

    result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)

    assert result["ok"], result["errors"]


def test_response_citing_critical_point_id_outside_allowed_fails():
    """Regression case vs the old weak validator: a response that would pass
    the legacy escenarios/discusion_grafos-name-only check but references a
    critical_point id outside the allowed context must be rejected."""
    context = _context()
    response = _valid_response(context)
    response["hallazgos"].append("Ver punto critico cp-2099-12-31 para mas detalle.")

    result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)

    assert not result["ok"]
    assert any("cp-2099-12-31" in error for error in result["errors"])


def test_response_with_date_outside_allowed_fails():
    context = _context()
    response = _valid_response(context)
    response["hallazgos"].append("El evento del 2099-12-31 fue relevante.")

    result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)

    assert not result["ok"]
    assert any("2099-12-31" in error for error in result["errors"])


def test_response_citing_fabricated_scenario_name_fails():
    context = _context()
    response = _valid_response(context)
    response["escenarios"][0]["nombre"] = "Escenario inventado que no existe en el contexto"

    result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)

    assert not result["ok"]
    assert any("Escenario inventado" in error for error in result["errors"])


def test_weak_check_regression_prevented_old_validator_passes_new_one_rejects():
    """Direct comparison: build a response that the OLD, weak
    `circuit_analysis.validar_respuesta_inferencia` (name-completeness-only)
    would accept, but which cites a critical_point id outside the allowed
    context — the new strict validator must reject it."""
    context = _context()
    response = _valid_response(context)
    response["discusion_grafos"] = {
        "periodo_completo": "Lectura general del periodo completo, ver cp-2099-12-31.",
    }

    old_result = validar_respuesta_inferencia(json.dumps(response, ensure_ascii=False), context)
    assert old_result["ok"] is True, old_result["errors"]

    new_result = validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)
    assert new_result["ok"] is False


def test_validation_is_side_effect_free_on_input_context():
    context = _context()
    snapshot = copy.deepcopy(context)
    response = _valid_response(context)

    validar_respuesta_inferencia_strict(json.dumps(response, ensure_ascii=False), context)

    assert context == snapshot


# --- Provenance wrapper ---


def test_provenance_rule_allow_list_is_hermetic():
    assert INFERENCE_PROVENANCE_RULES == {
        "01_structured_context_builder",
        "02_circuit_scenario_interpreter",
        "03_uiti_vano_behavior_explainer",
        "04_graph_connectivity_guardrails",
        "05_llm_output_validator",
        "06_inference_output_contract",
    }
    assert INFERENCE_AGENT_ID == "inference"


def test_validar_provenance_inferencia_passes_when_every_data_ref_resolves():
    context = _context()
    response = _valid_response_with_provenance(context)

    result = validar_provenance_inferencia(response, context)

    assert result["ok"], result["errors"]
    assert result["errors"] == []


def test_validar_provenance_inferencia_fails_on_unknown_variable():
    context = _context()
    response = _valid_response_with_provenance(context)
    response["escenarios"][0]["provenance"]["data_ref"] = ["VARIABLE_INEXISTENTE"]

    result = validar_provenance_inferencia(response, context)

    assert not result["ok"]
    assert any("VARIABLE_INEXISTENTE" in error for error in result["errors"])


def test_validar_provenance_inferencia_fails_on_unknown_date():
    context = _context()
    response = _valid_response_with_provenance(context)
    response["escenarios"][0]["provenance"]["data_ref"] = ["2099-12-31"]

    result = validar_provenance_inferencia(response, context)

    assert not result["ok"]
    assert any("2099-12-31" in error for error in result["errors"])


def test_validar_provenance_inferencia_fails_on_unknown_critical_point_id():
    context = _context()
    response = _valid_response_with_provenance(context)
    response["discusion_grafos"][0]["provenance"]["data_ref"] = ["cp-2099-12-31"]

    result = validar_provenance_inferencia(response, context)

    assert not result["ok"]
    assert any("cp-2099-12-31" in error for error in result["errors"])


def test_validar_provenance_inferencia_fails_when_agent_does_not_match():
    context = _context()
    response = _valid_response_with_provenance(context)
    response["escenarios"][0]["provenance"]["agent"] = "some-other-agent"

    result = validar_provenance_inferencia(response, context)

    assert not result["ok"]
    assert any("agent" in error.lower() for error in result["errors"])


def test_validar_provenance_inferencia_fails_when_rule_not_in_allow_list():
    context = _context()
    response = _valid_response_with_provenance(context)
    response["escenarios"][0]["provenance"]["rule"] = "not-a-real-rule"

    result = validar_provenance_inferencia(response, context)

    assert not result["ok"]
    assert any("rule" in error.lower() for error in result["errors"])


def test_validar_provenance_inferencia_ignores_items_without_provenance_key():
    context = _context()
    response = _valid_response(context)

    result = validar_provenance_inferencia(response, context)

    assert result["ok"], result["errors"]
    assert result["errors"] == []


def test_validar_provenance_inferencia_accepts_scenario_name_reference():
    context = _context()
    response = _valid_response_with_provenance(context)
    response["escenarios"][0]["provenance"]["data_ref"] = [_ESCENARIO_NOMBRE]

    result = validar_provenance_inferencia(response, context)

    assert result["ok"], result["errors"]
