from __future__ import annotations

import json

import pandas as pd

from chec_local_interpreter.expert_alignment import (
    construir_contexto_expert_alignment,
    construir_prompt_expert_alignment,
    extraer_fechas_informe,
    filtrar_discussiones_por_circuito,
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
    assert "Comparación de Reportes PDF" in skill_bundle
    assert "Priorización de Variables" in skill_bundle
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
    assert all(match["Circuito"] == "DON23L13" for match in matches)


def test_pdf_discussions_are_ignored_when_circuit_is_absent():
    fechas = [
        {"source": "critical_point", "fecha_inicio": "2026-01-10", "fecha_fin": "2026-01-10", "descripcion": "cp", "peso": 3.0},
    ]
    pdf_df = pd.DataFrame(
        [
            {"Circuito": "OTRO", "Fecha inicio": "2026-01-09", "Fecha fin": "2026-01-11", "Análisis": "UITI_VANO alto", "Evidencia": "Evidencia A"},
            {"Circuito": "DON23L14", "Fecha inicio": "2026-01-10", "Fecha fin": "2026-01-10", "Análisis": "Cercano pero otro circuito", "Evidencia": "Evidencia B"},
        ]
    )
    assert filtrar_discussiones_por_circuito(pdf_df, "DON23L13").empty
    matches = seleccionar_top_coincidencias_temporales(
        fechas_informe=fechas,
        pdf_df=pdf_df,
        circuito_interes="DON23L13",
        top_k=2,
    )
    assert matches == []


def test_pdf_discussion_filter_accepts_normalized_exact_circuit():
    pdf_df = pd.DataFrame(
        [
            {"Circuito": " don-23l13 ", "Fecha inicio": "2026-01-09", "Fecha fin": "2026-01-11", "Análisis": "A", "Evidencia": "B"},
            {"Circuito": "DON23L14", "Fecha inicio": "2026-01-09", "Fecha fin": "2026-01-11", "Análisis": "C", "Evidencia": "D"},
        ]
    )
    filtered = filtrar_discussiones_por_circuito(pdf_df, "DON23L13")
    assert len(filtered) == 1
    assert filtered.iloc[0]["Circuito"] == " don-23l13 "


def test_context_builder_drops_pdf_matches_from_other_circuits():
    context = construir_contexto_expert_alignment(
        circuito="DON23L13",
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
        fechas_informe=[],
        validation_data={},
        inference_validation_data={},
        pdf_expert_matches=[
            {"Circuito": "OTRO", "Fecha inicio": "2026-01-01", "Fecha fin": "2026-01-02", "Análisis": "No usar", "Evidencia": "No usar"},
            {"Circuito": " don-23l13 ", "Fecha inicio": "2026-01-03", "Fecha fin": "2026-01-04", "Análisis": "Usar", "Evidencia": "Usar"},
        ],
        variables_modelo_predictivo=["CNT_TRF"],
    )
    assert len(context["pdf_expert_matches"]) == 1
    assert context["pdf_expert_matches"][0]["Análisis"] == "Usar"
    assert context["modelo_experto_disponible"] is True
    assert context["fuentes_usadas"] == ["Agente Descriptor", "Agente predictivo", "Modelo Experto"]


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
    assert result["data"]["coincidencias"][0]["fuentes"] == ["Agente Descriptor", "DON23L13.pdf"]
    assert result["data"]["variables_a_priorizar"][0]["fuentes_que_la_respaldan"] == ["Agente Descriptor", "DON23L13.pdf"]
    assert result["data"]["contexto"]["fuentes_usadas"] == ["Agente Descriptor", "Agente predictivo", "Modelo Experto"]
    assert result["data"]["contexto"]["modelo_experto_disponible"] is True

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


def test_validar_respuesta_expert_alignment_rejects_bare_causa_word():
    context = {
        "periodo_informe": {"inicio": "2026-01-01", "fin": "2026-01-31"},
        "fechas_informe": [],
        "llm1_analysis": {"period_synthesis": ""},
        "llm2_inference_analysis": {"escenarios": []},
        "variables_modelo_predictivo": [],
        "pdf_expert_matches": [],
    }
    output = {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}, "n_filas_expertas_comparadas": 0},
        "coincidencias": [],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [],
        "sintesis_final": "La vegetación es la causa directa del evento observado.",
    }
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert not result["ok"]
    assert any("causa" in error.lower() for error in result["errors"])

    # A word that merely contains "causa" as a substring (e.g. "encausar", a
    # distinct Spanish verb meaning "to channel/prosecute") must not be
    # falsely flagged by a naive substring check.
    output["sintesis_final"] = "El equipo procederá a encausar el proceso operativo."
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert not any("causa" in error.lower() for error in result["errors"])

    output["sintesis_final"] = "El evento causó daños en la estructura."
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert not result["ok"]
    assert any("causó" in error for error in result["errors"])


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
    assert "Agente Descriptor" in html
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


def test_expert_alignment_runs_with_available_agents_when_no_pdf_matches():
    context = construir_contexto_expert_alignment(
        circuito="DON23L13",
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
        fechas_informe=[{"source": "critical_point", "fecha_inicio": "2026-01-10", "fecha_fin": "2026-01-10"}],
        validation_data={"period_synthesis": "UITI_VANO sube en el punto crítico."},
        inference_validation_data={"hallazgos": ["El modelo resalta CNT_TRF."]},
        pdf_expert_matches=[],
        variables_modelo_predictivo=["CNT_TRF", "CNT_VN"],
        inference_context_package={
            "escenarios": [
                {
                    "nombre": "Top por UITI_VANO",
                    "top_variables": [{"variable": "CNT_TRF", "score": 0.9}],
                    "modos": [],
                }
            ]
        },
    )
    prompt = construir_prompt_expert_alignment(context, "Skill bundle")
    assert context["fuentes_disponibles"] == ["Agente Descriptor", "Agente predictivo"]
    assert context["modelo_experto_disponible"] is False
    assert context["modelo_experto_razon"]
    assert "solo entre Agente Descriptor y Agente predictivo" in prompt

    output = {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}, "n_filas_expertas_comparadas": 0},
        "coincidencias": [{"tema": "UITI_VANO y CNT_TRF", "fuentes": ["Agente Descriptor", "Agente predictivo"], "explicacion": "Ambos agentes apuntan al mismo periodo crítico."}],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [{"variable": "CNT_TRF", "prioridad": "media", "fuentes_que_la_respaldan": ["Agente predictivo"], "justificacion": "Es señal del modelo.", "tipo_de_validacion_sugerida": "Revisar conexión en grafos."}],
        "sintesis_final": "La comparación queda limitada a las dos fuentes disponibles.",
    }
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert result["ok"], result["errors"]


def test_expert_alignment_rejects_expert_findings_without_pdf_matches():
    context = construir_contexto_expert_alignment(
        circuito="DON23L13",
        periodo_inicio="2026-01-01",
        periodo_fin="2026-01-31",
        fechas_informe=[],
        validation_data={},
        inference_validation_data={},
        pdf_expert_matches=[],
        variables_modelo_predictivo=["CNT_TRF"],
    )
    output = {
        "contexto": {"circuito": "DON23L13", "periodo": {"inicio": "2026-01-01", "fin": "2026-01-31"}, "n_filas_expertas_comparadas": 0},
        "coincidencias": [{"tema": "Supuesto PDF", "fuentes": ["PDF_EXPERTO"], "explicacion": "Un reporte lo respalda."}],
        "diferencias": [],
        "hallazgos_expertos_no_cubiertos": [{"tema": "Hallazgo experto inexistente"}],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [],
        "sintesis_final": "Síntesis.",
    }
    result = validar_respuesta_expert_alignment(json.dumps(output, ensure_ascii=False), context)
    assert not result["ok"]
    assert any("fuentes visibles" in error for error in result["errors"])
    assert any("hallazgos_expertos_no_cubiertos" in error for error in result["errors"])
