from __future__ import annotations

import json

import pandas as pd

from chec_local_interpreter.expert_alignment import (
    construir_contexto_expert_alignment,
    extraer_fechas_informe,
    seleccionar_top_coincidencias_temporales,
    validar_respuesta_expert_alignment,
)
from chec_local_interpreter.llm_skills import assemble_skill_bundle, list_available_skills, verify_required_skills
from chec_local_interpreter.plotting import render_expert_alignment_tab


def test_expert_alignment_skill_profile_loads():
    assert verify_required_skills(profile="expert_alignment") == []
    assert list_available_skills(profile="expert_alignment") == [
        "01_pdf_report_comparison.md",
        "02_predictive_variable_prioritization.md",
        "03_graph_context_for_alignment.md",
    ]
    skill_bundle = assemble_skill_bundle(profile="expert_alignment")
    assert "PDF Report Comparison" in skill_bundle
    assert "Priorizacion de Variables" in skill_bundle
    assert "Contexto de Grafos" in skill_bundle


def test_extraer_fechas_informe_collects_multiple_sources():
    records = extraer_fechas_informe(
        validation_data={"key_findings": [{"evidence": [{"date": "2026-01-02"}]}]},
        inference_validation_data={"contexto": {"periodo": {"inicio": "2026-01-01", "fin": "2026-01-10"}}},
        critical_points=[{"fecha_dia": "2026-01-05", "critical_point_id": "cp-2026-01-05"}],
        fecha_inicio="2026-01-01",
        fecha_fin="2026-01-31",
        fechas_interes=["2026-01-06"],
    )
    assert {"LLM1", "LLM2", "critical_point", "context"}.issubset({item["source"] for item in records})
    assert any(item["fecha_inicio"] == "2026-01-05" and item["peso"] == 3.0 for item in records)


def test_seleccionar_top_coincidencias_temporales_prefers_overlap_and_circuit():
    fechas = [
        {"source": "critical_point", "fecha_inicio": "2026-01-10", "fecha_fin": "2026-01-10", "descripcion": "cp", "peso": 3.0},
        {"source": "context", "fecha_inicio": "2026-02-01", "fecha_fin": "2026-02-28", "descripcion": "global", "peso": 0.5},
    ]
    pdf_df = pd.DataFrame(
        [
            {"Circuito": "DON23L13", "Fecha inicio": "2026-01-09", "Fecha fin": "2026-01-11", "Análisis": "UITI_VANO alto", "Evidencia": "Evidencia A"},
            {"Circuito": "OTRO", "Fecha inicio": "2026-03-01", "Fecha fin": "2026-03-02", "Análisis": "Distante", "Evidencia": "Evidencia B"},
        ]
    )
    matches = seleccionar_top_coincidencias_temporales(
        fechas_informe=fechas,
        pdf_df=pdf_df,
        circuito_interes="DON23L13",
        top_k=2,
    )
    assert matches[0]["Circuito"] == "DON23L13"
    assert matches[0]["overlap_days"] == 1
    assert matches[0]["matched_source"] == "critical_point"


def test_validar_respuesta_expert_alignment_checks_evidence_dates_and_variables():
    context = {
        "periodo_informe": {"inicio": "2026-01-01", "fin": "2026-01-31"},
        "fechas_informe": [{"source": "critical_point", "fecha_inicio": "2026-01-10", "fecha_fin": "2026-01-10"}],
        "llm1_analysis": {"period_synthesis": "UITI_VANO y NR_T aparecen en el periodo."},
        "llm2_inference_analysis": {"escenarios": [{"top_variables": ["UITI_VANO"]}]},
        "variables_modelo_predictivo": ["NR_T"],
        "pdf_expert_matches": [
            {
                "Circuito": "DON23L13",
                "Fecha inicio": "2026-01-09",
                "Fecha fin": "2026-01-11",
                "Análisis": "UITI_VANO alto",
                "Evidencia": "Evidencia experta verificable",
            }
        ],
    }
    output = {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}, "n_filas_expertas_comparadas": 1},
        "coincidencias": [
            {
                "tema": "UITI_VANO alto",
                "fechas_relacionadas": ["2026-01-10"],
                "fuentes": ["LLM1", "PDF_EXPERTO"],
                "explicacion": "Coinciden temporalmente.",
                "evidencia_pdf": "Evidencia experta verificable",
            }
        ],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [
            {
                "variable": "NR_T",
                "prioridad": "alta",
                "fuentes_que_la_respaldan": ["LLM1", "PDF_EXPERTO"],
                "justificacion": "Aparece en las fuentes comparadas.",
                "tipo_de_validacion_sugerida": "Revisar eventos fuente.",
            }
        ],
        "sintesis_final": "La comparación es consistente y requiere validación operacional.",
    }
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert result["ok"], result["errors"]
    assert result["data"]["coincidencias"][0]["fuentes"] == ["Agente base", "DON23L13.pdf"]
    assert result["data"]["variables_a_priorizar"][0]["fuentes_que_la_respaldan"] == ["Agente base", "DON23L13.pdf"]

    output["variables_a_priorizar"][0]["variable"] = "UITI_VANO"
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert not result["ok"]
    assert any("Variable no encontrada" in error for error in result["errors"])

    output["variables_a_priorizar"][0]["variable"] = "DDT"
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert not result["ok"]
    assert any("Variable no encontrada" in error for error in result["errors"])

    output["variables_a_priorizar"][0]["variable"] = "VARIABLE_NUEVA"
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert not result["ok"]
    assert any("Variable no encontrada" in error for error in result["errors"])

    output["variables_a_priorizar"][0]["variable"] = "NR_T (Vegetación)"
    context["llm1_analysis"]["period_synthesis"] += " NR_T aparece como riesgo de vegetacion."
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert result["ok"], result["errors"]


def test_render_expert_alignment_tab_uses_html_not_raw_json():
    analysis = {
        "contexto": {
            "circuito": "DON23L13",
            "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"},
            "n_filas_expertas_comparadas": 1,
        },
        "coincidencias": [
            {
                "tema": "UITI_VANO alto",
                "fechas_relacionadas": ["2026-01-10"],
                "fuentes": ["LLM1", "PDF_EXPERTO"],
                "explicacion": "Coinciden en la ventana.",
                "evidencia_pdf": "Evidencia experta",
            }
        ],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [
            {
                "variable": "NR_T",
                "prioridad": "alta",
                "fuentes_que_la_respaldan": ["LLM1"],
                "justificacion": "Aparece en la comparación.",
                "tipo_de_validacion_sugerida": "Revisión operacional.",
            }
        ],
        "sintesis_final": "Síntesis breve.",
    }
    html = render_expert_alignment_tab(analysis)
    assert "Comparación con reportes expertos" in html
    assert "UITI_VANO alto" in html
    assert "Fuentes:" in html
    assert "Agente base" in html
    assert "reportes expertos" in html
    assert '"coincidencias"' not in html
    assert "<table" in html


def test_context_includes_predictive_model_signals_for_priorities():
    context = construir_contexto_expert_alignment(
        circuito="DON23L13",
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
        fechas_informe=[],
        validation_data={},
        inference_validation_data={},
        pdf_expert_matches=[],
        variables_modelo_predictivo=["CNT_TRF", "CNT_VN", "TIPO"],
        inference_context_package={
            "escenarios": [
                {
                    "nombre": "Top por UITI_VANO",
                    "top_variables": [{"variable": "CNT_TRF", "score": 0.9}, {"variable": "TIPO", "score": 0.8}],
                    "modos": [{"modo": "Activos", "variables": ["CNT_VN"]}],
                }
            ]
        },
    )
    raw = {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}, "n_filas_expertas_comparadas": 0},
        "coincidencias": [{"tema": "El modelo predictivo resalta transformadores y vanos", "fuentes": ["Agente predictivo"], "explicacion": "Hay consistencia operacional."}],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [],
        "sintesis_final": "Priorizar conexiones del modelo.",
    }
    result = validar_respuesta_expert_alignment(json.dumps(raw, ensure_ascii=False), context)
    assert result["ok"], result["errors"]
    variables = {item["variable"] for item in result["data"]["variables_a_priorizar"]}
    assert {"CNT_TRF", "CNT_VN"}.issubset(variables)
