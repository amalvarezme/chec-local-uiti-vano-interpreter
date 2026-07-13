from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from chec_local_interpreter.expert_alignment import (
    PRIOR_REPORT_PDF_ROW_INDEX_OFFSET,
    _allowed_pdf_row_indexes,
    _compact_pdf_matches,
    _normalize_output_context_metadata,
    _normalize_visible_sources,
    _pdf_source_names,
    construir_contexto_expert_alignment,
    construir_prompt_expert_alignment,
    extraer_fechas_informe,
    filtrar_discussiones_por_circuito,
    normalizar_reporte_previo_como_matches,
    seleccionar_reporte_previo_mas_reciente,
    seleccionar_top_coincidencias_temporales,
    validar_respuesta_expert_alignment,
)
from chec_local_interpreter.llm_skills import assemble_skill_bundle, list_available_skills, verify_required_skills
from chec_local_interpreter.plotting import render_expert_alignment_tab


def _write_expert_alignment_out(run_dir: Path, *, ok: bool = True, data: dict | None = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"ok": ok, "data": data if data is not None else {}}
    (run_dir / "expert-alignment.out.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_expert_alignment_skill_profile_loads():
    assert verify_required_skills(profile="expert_alignment") == []
    assert list_available_skills(profile="expert_alignment") == [
        "01_pdf_report_comparison.md",
        "02_predictive_variable_prioritization.md",
        "03_graph_context_for_alignment.md",
        "04_prior_report_continuity.md",
    ]
    skill_bundle = assemble_skill_bundle(profile="expert_alignment")
    assert "Comparación de Reportes PDF" in skill_bundle
    assert "Priorización de Variables" in skill_bundle
    assert "Contexto de Grafos" in skill_bundle
    assert "Continuidad con el Reporte Previo del Circuito" in skill_bundle


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


# ---------------------------------------------------------------------------
# Phase 1 (PR 1): prior-run discovery and selection
#
# `seleccionar_reporte_previo_mas_reciente` and `normalizar_reporte_previo_como_matches`
# are standalone/pure and NOT wired into any pipeline consumer yet (that
# wiring is PR 2 scope, tasks 3.1-5.2) -- these tests exercise the two new
# functions directly.
# ---------------------------------------------------------------------------


class TestSeleccionarReportePrevioMasReciente:
    def test_multiple_qualifying_prior_runs_returns_newest(self, tmp_path):
        circuit_dir = tmp_path / "runs" / "C1"
        older = circuit_dir / "20260101T000000000000"
        middle = circuit_dir / "20260102T000000000000"
        newest = circuit_dir / "20260103T000000000000"
        for run_dir in (older, middle, newest):
            _write_expert_alignment_out(run_dir)
        current_run_dir = circuit_dir / "20260104T000000000000"
        current_run_dir.mkdir(parents=True)

        result = seleccionar_reporte_previo_mas_reciente(current_run_dir)

        assert result == newest

    def test_prior_run_missing_its_own_expert_alignment_output_is_skipped(self, tmp_path):
        circuit_dir = tmp_path / "runs" / "C1"
        incomplete = circuit_dir / "20260101T000000000000"
        incomplete.mkdir(parents=True)
        (incomplete / "historical.out.json").write_text(
            json.dumps({"ok": True, "data": {}}), encoding="utf-8"
        )
        (incomplete / "inference.out.json").write_text(
            json.dumps({"ok": True, "data": {}}), encoding="utf-8"
        )
        # No expert-alignment.out.json written for `incomplete` -- it is the
        # ONLY prior candidate, so the function must return None even though
        # historical+inference evidence exists.
        current_run_dir = circuit_dir / "20260102T000000000000"
        current_run_dir.mkdir(parents=True)

        result = seleccionar_reporte_previo_mas_reciente(current_run_dir)

        assert result is None

    def test_prior_run_missing_expert_alignment_output_is_skipped_in_favor_of_qualifying_sibling(
        self, tmp_path
    ):
        circuit_dir = tmp_path / "runs" / "C1"
        qualifying = circuit_dir / "20260101T000000000000"
        _write_expert_alignment_out(qualifying)
        incomplete = circuit_dir / "20260102T000000000000"
        incomplete.mkdir(parents=True)
        current_run_dir = circuit_dir / "20260103T000000000000"
        current_run_dir.mkdir(parents=True)

        result = seleccionar_reporte_previo_mas_reciente(current_run_dir)

        assert result == qualifying

    def test_zero_qualifying_prior_runs_returns_none(self, tmp_path):
        circuit_dir = tmp_path / "runs" / "C1"
        current_run_dir = circuit_dir / "20260101T000000000000"
        current_run_dir.mkdir(parents=True)

        result = seleccionar_reporte_previo_mas_reciente(current_run_dir)

        assert result is None

    def test_current_run_dir_is_self_excluded_even_if_it_has_a_valid_output(self, tmp_path):
        circuit_dir = tmp_path / "runs" / "C1"
        current_run_dir = circuit_dir / "20260101T000000000000"
        # Simulate mid-run reentry: the CURRENT run already wrote its own
        # valid expert-alignment.out.json before selection runs again.
        _write_expert_alignment_out(current_run_dir)

        result = seleccionar_reporte_previo_mas_reciente(current_run_dir)

        assert result is None

    def test_self_exclusion_uses_resolved_path_comparison(self, tmp_path):
        circuit_dir = tmp_path / "runs" / "C1"
        current_run_dir = circuit_dir / "20260101T000000000000"
        _write_expert_alignment_out(current_run_dir)

        # A non-normalized (but equivalent) path to the same directory must
        # still be excluded.
        noisy_path = circuit_dir / "." / "20260101T000000000000"

        result = seleccionar_reporte_previo_mas_reciente(noisy_path)

        assert result is None


# ---------------------------------------------------------------------------
# Phase 2 (PR 1): prior-report normalization
# ---------------------------------------------------------------------------


def _write_prior_expert_alignment_data(
    run_dir: Path,
    *,
    periodo_inicio: str = "2026-01-01",
    periodo_fin: str = "2026-01-10",
    coincidencias: list | None = None,
    diferencias: list | None = None,
    sintesis_final: str = "La comparación previa fue consistente y requiere validación.",
) -> None:
    data = {
        "contexto": {
            "circuito": "C1",
            "periodo": {"inicio": periodo_inicio, "fin": periodo_fin},
            "n_filas_expertas_comparadas": 1,
        },
        "coincidencias": coincidencias if coincidencias is not None else [
            {
                "tema": "UITI_VANO elevado en el periodo previo",
                "fuentes": ["Agente Descriptor", "Agente predictivo"],
                "explicacion": "Ambas fuentes coincidieron en el periodo previo.",
            }
        ],
        "diferencias": diferencias if diferencias is not None else [],
        "hallazgos_expertos_no_cubiertos": [],
        "hallazgos_modelo_no_respaldados_por_pdf": [],
        "variables_a_priorizar": [],
        "sintesis_final": sintesis_final,
    }
    _write_expert_alignment_out(run_dir, data=data)


_REQUIRED_PDF_EXPERT_MATCH_KEYS = (
    "Circuito",
    "Fecha inicio",
    "Fecha fin",
    "Análisis",
    "Evidencia",
    "matched_source",
    "matched_fecha_inicio",
    "matched_fecha_fin",
    "matched_descripcion",
    "temporal_score",
    "overlap_days",
    "distance_days",
    "pdf_row_index",
)


class TestNormalizarReportePrevioComoMatches:
    def test_returned_records_contain_every_pdf_expert_matches_required_key(self, tmp_path):
        prior_run_dir = tmp_path / "runs" / "C1" / "20260101T000000000000"
        _write_prior_expert_alignment_data(prior_run_dir)
        fechas_informe = [
            {
                "source": "critical_point",
                "fecha_inicio": "2026-01-05",
                "fecha_fin": "2026-01-05",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ]

        records = normalizar_reporte_previo_como_matches(
            prior_run_dir, "C1", fechas_informe, top_k=3
        )

        assert records
        for record in records:
            for key in _REQUIRED_PDF_EXPERT_MATCH_KEYS:
                assert key in record, f"missing key {key!r} in {record!r}"
            assert record["Circuito"] == "C1"

    def test_rows_are_built_from_sintesis_final_and_top_coincidencias_diferencias(self, tmp_path):
        prior_run_dir = tmp_path / "runs" / "C1" / "20260101T000000000000"
        _write_prior_expert_alignment_data(
            prior_run_dir,
            coincidencias=[
                {"tema": "Coincidencia 1", "explicacion": "Explicación 1"},
            ],
            diferencias=[
                {"tema": "Diferencia 1", "explicacion": "Explicación 2"},
            ],
            sintesis_final="Síntesis del reporte previo.",
        )
        fechas_informe = [
            {
                "source": "critical_point",
                "fecha_inicio": "2026-01-05",
                "fecha_fin": "2026-01-05",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ]

        records = normalizar_reporte_previo_como_matches(
            prior_run_dir, "C1", fechas_informe, top_k=3
        )

        analisis_values = {record["Análisis"] for record in records}
        # sintesis_final + both coincidencias/diferencias items should all be
        # representable as candidate rows (top_k=3 keeps all 3 here).
        assert len(records) == 3
        assert "Coincidencia 1" in analisis_values
        assert "Diferencia 1" in analisis_values

    def test_dates_are_sourced_from_prior_contexto_periodo(self, tmp_path):
        prior_run_dir = tmp_path / "runs" / "C1" / "20260101T000000000000"
        _write_prior_expert_alignment_data(
            prior_run_dir, periodo_inicio="2025-12-01", periodo_fin="2025-12-15"
        )
        fechas_informe = [
            {
                "source": "critical_point",
                "fecha_inicio": "2025-12-10",
                "fecha_fin": "2025-12-10",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ]

        records = normalizar_reporte_previo_como_matches(
            prior_run_dir, "C1", fechas_informe, top_k=3
        )

        assert records
        for record in records:
            assert record["Fecha inicio"] == "2025-12-01"
            assert record["Fecha fin"] == "2025-12-15"

    def test_no_qualifying_evidence_returns_empty_list(self, tmp_path):
        prior_run_dir = tmp_path / "runs" / "C1" / "20260101T000000000000"
        _write_prior_expert_alignment_data(
            prior_run_dir, coincidencias=[], diferencias=[], sintesis_final=""
        )
        fechas_informe = [
            {
                "source": "critical_point",
                "fecha_inicio": "2026-01-05",
                "fecha_fin": "2026-01-05",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ]

        records = normalizar_reporte_previo_como_matches(
            prior_run_dir, "C1", fechas_informe, top_k=3
        )

        assert records == []

    def test_pdf_row_index_is_offset_and_recognized_by_allowed_pdf_row_indexes(self, tmp_path):
        prior_run_dir = tmp_path / "runs" / "C1" / "20260101T000000000000"
        _write_prior_expert_alignment_data(prior_run_dir)
        fechas_informe = [
            {
                "source": "critical_point",
                "fecha_inicio": "2026-01-05",
                "fecha_fin": "2026-01-05",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ]

        records = normalizar_reporte_previo_como_matches(
            prior_run_dir, "C1", fechas_informe, top_k=3
        )

        assert records
        for record in records:
            assert record["pdf_row_index"] >= PRIOR_REPORT_PDF_ROW_INDEX_OFFSET

        fake_context = {"pdf_expert_matches": records}
        allowed = _allowed_pdf_row_indexes(fake_context)
        assert str(records[0]["pdf_row_index"]) in allowed

    def test_records_carry_source_kind_baja_confidence_and_penalized_temporal_score(self, tmp_path):
        """Phase 3 (PR 2): prior-report records must be marked as lower-trust
        continuity evidence, distinct from PDF-sourced `pdf_expert_matches`
        rows: `source_kind: "prior_report"`, `confidence: "baja"`, and a
        `temporal_score` scaled by a 0.5x penalty relative to what the SAME
        matcher would compute for an equivalent PDF-sourced row (same dates,
        same circuit, same fechas_informe window)."""
        prior_run_dir = tmp_path / "runs" / "C1" / "20260101T000000000000"
        _write_prior_expert_alignment_data(
            prior_run_dir,
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-10",
            coincidencias=[{"tema": "UITI_VANO elevado", "explicacion": "Explicación previa."}],
            diferencias=[],
            sintesis_final="",
        )
        fechas_informe = [
            {
                "source": "critical_point",
                "fecha_inicio": "2026-01-05",
                "fecha_fin": "2026-01-05",
                "descripcion": "cp",
                "peso": 3.0,
            }
        ]

        records = normalizar_reporte_previo_como_matches(
            prior_run_dir, "C1", fechas_informe, top_k=3
        )

        assert records
        for record in records:
            assert record["source_kind"] == "prior_report"
            assert record["confidence"] == "baja"

        # Equivalent PDF-sourced row: identical dates/circuit/Análisis/Evidencia
        # (the candidate row `normalizar_reporte_previo_como_matches` builds
        # internally carries the `coincidencias` item's `explicacion` as
        # `Evidencia`), run through the SAME underlying matcher directly (no
        # prior-report post-processing), to compute the unpenalized reference
        # score.
        equivalent_pdf_df = pd.DataFrame(
            [
                {
                    "Circuito": "C1",
                    "Fecha inicio": "2026-01-01",
                    "Fecha fin": "2026-01-10",
                    "Análisis": "UITI_VANO elevado",
                    "Evidencia": "Explicación previa.",
                }
            ]
        )
        pdf_matches = seleccionar_top_coincidencias_temporales(
            fechas_informe=fechas_informe,
            pdf_df=equivalent_pdf_df,
            circuito_interes="C1",
            top_k=3,
        )
        assert pdf_matches
        unpenalized_score = pdf_matches[0]["temporal_score"]
        matching_record = next(r for r in records if r["Análisis"] == "UITI_VANO elevado")
        assert matching_record["temporal_score"] == round(unpenalized_score * 0.5, 6)


# ---------------------------------------------------------------------------
# Phase 4 (PR 2): wiring -- availability, renderers, prompt, no-op guard
# ---------------------------------------------------------------------------


_PDF_ONLY_MATCH = {
    "Circuito": "DON23L13",
    "Fecha inicio": "2026-01-09",
    "Fecha fin": "2026-01-11",
    "Análisis": "UITI_VANO alto",
    "Evidencia": "Evidencia A",
    "matched_source": "critical_point",
    "matched_fecha_inicio": "2026-01-10",
    "matched_fecha_fin": "2026-01-10",
    "matched_descripcion": "cp",
    "temporal_score": 3.3,
    "overlap_days": 1,
    "distance_days": 0,
    "pdf_row_index": 0,
}

_PRIOR_REPORT_MATCH = {
    **{k: v for k, v in _PDF_ONLY_MATCH.items() if k not in ("pdf_row_index", "temporal_score")},
    "temporal_score": 1.65,
    "pdf_row_index": PRIOR_REPORT_PDF_ROW_INDEX_OFFSET,
    "source_kind": "prior_report",
    "confidence": "baja",
}


class TestCompactPdfMatchesCarriesProvenance:
    def test_source_kind_and_confidence_pass_through_when_present(self):
        compact = _compact_pdf_matches([_PRIOR_REPORT_MATCH])
        assert compact[0]["source_kind"] == "prior_report"
        assert compact[0]["confidence"] == "baja"

    def test_pdf_only_records_have_no_source_kind_or_confidence_keys(self):
        """Regression guard: PDF-only records (no `source_kind`) must not
        gain new keys -- required for the byte-identical no-op path."""
        compact = _compact_pdf_matches([_PDF_ONLY_MATCH])
        assert "source_kind" not in compact[0]
        assert "confidence" not in compact[0]


class TestConstruirContextoAvailabilitySplit:
    def test_modelo_experto_disponible_excludes_prior_report_records(self):
        context = construir_contexto_expert_alignment(
            circuito="DON23L13",
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-31",
            fechas_informe=[],
            validation_data={},
            inference_validation_data={},
            pdf_expert_matches=[_PRIOR_REPORT_MATCH],
        )
        assert context["modelo_experto_disponible"] is False
        assert context["reporte_previo_disponible"] is True

    def test_modelo_experto_disponible_true_when_pdf_only_records_present(self):
        context = construir_contexto_expert_alignment(
            circuito="DON23L13",
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-31",
            fechas_informe=[],
            validation_data={},
            inference_validation_data={},
            pdf_expert_matches=[_PDF_ONLY_MATCH],
        )
        assert context["modelo_experto_disponible"] is True
        assert "reporte_previo_disponible" not in context

    def test_visible_source_is_reporte_previo_del_circuito_not_pdf_name(self):
        context = construir_contexto_expert_alignment(
            circuito="DON23L13",
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-31",
            fechas_informe=[],
            validation_data={},
            inference_validation_data={},
            pdf_expert_matches=[_PRIOR_REPORT_MATCH],
        )
        assert "Reporte previo del circuito" in context["fuentes_usadas"]
        assert "DON23L13.pdf" not in context["fuentes_usadas"]


class TestPdfSourceNamesExcludesPriorReport:
    def test_pdf_source_names_ignores_prior_report_rows(self):
        context = {"pdf_expert_matches": [_PRIOR_REPORT_MATCH]}
        assert _pdf_source_names(context) == []

    def test_pdf_source_names_unaffected_for_pdf_only_fixtures(self):
        context = {"pdf_expert_matches": [_PDF_ONLY_MATCH]}
        assert _pdf_source_names(context) == ["DON23L13.pdf"]


class TestNormalizeVisibleSourcesRecognizesPriorReport:
    def test_reporte_previo_phrase_maps_to_canonical_name(self):
        context = {"pdf_expert_matches": [_PRIOR_REPORT_MATCH]}
        assert _normalize_visible_sources(["Reporte previo del circuito"], context) == [
            "Reporte previo del circuito"
        ]

    def test_pdf_only_fixture_unaffected(self):
        context = {"pdf_expert_matches": [_PDF_ONLY_MATCH]}
        assert _normalize_visible_sources(["Modelo Experto"], context) == ["DON23L13.pdf"]


class TestNormalizeOutputContextMetadataRecognizesPriorReport:
    def test_expert_available_stays_false_with_only_prior_report_rows(self):
        context = {
            "pdf_expert_matches": [_PRIOR_REPORT_MATCH],
            "fuentes_usadas": ["Agente Descriptor", "Agente predictivo", "Reporte previo del circuito"],
        }
        data = {"contexto": {}}
        errors = _normalize_output_context_metadata(data, context)
        assert errors == []
        assert data["contexto"]["modelo_experto_disponible"] is False

    def test_pdf_only_fixture_unaffected(self):
        context = {"pdf_expert_matches": [_PDF_ONLY_MATCH]}
        data = {"contexto": {}}
        errors = _normalize_output_context_metadata(data, context)
        assert errors == []
        assert data["contexto"]["modelo_experto_disponible"] is True


class TestConstruirPromptMentionsPriorReportOnlyWhenPresent:
    def test_prompt_mentions_reporte_previo_source_when_present(self):
        context = construir_contexto_expert_alignment(
            circuito="DON23L13",
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-31",
            fechas_informe=[],
            validation_data={},
            inference_validation_data={},
            pdf_expert_matches=[_PRIOR_REPORT_MATCH],
        )
        prompt = construir_prompt_expert_alignment(context, "Skill bundle")
        assert "Reporte previo del circuito" in prompt

    def test_prompt_omits_reporte_previo_source_when_absent(self):
        context = construir_contexto_expert_alignment(
            circuito="DON23L13",
            periodo_inicio="2026-01-01",
            periodo_fin="2026-01-31",
            fechas_informe=[],
            validation_data={},
            inference_validation_data={},
            pdf_expert_matches=[],
        )
        prompt = construir_prompt_expert_alignment(context, "Skill bundle")
        assert "Reporte previo del circuito" not in prompt
