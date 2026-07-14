from __future__ import annotations

import pandas as pd

from chec_local_interpreter.reports.report_workflow import (
    build_auto_simulator_prompt,
    build_inference_regeneration_prompt,
    compact_auto_simulation_context,
    compact_expert_alignment_context,
    compact_inference_context,
    select_rows_by_percentile,
    top_percentile_label,
    validate_auto_simulator_response,
    variables_from_inference,
)


def test_select_rows_by_percentile_sorts_selected_rows():
    df = pd.DataFrame({"metric": [1, 10, 5], "UITI_VANO_PROM": [3, 1, 2]})

    selected, threshold = select_rows_by_percentile(df, "metric", 50)

    assert threshold == 5.0
    assert selected["metric"].tolist() == [10, 5]
    assert top_percentile_label(95.0) == "P95"


def test_compact_inference_context_detects_graph_sections():
    context = {
        "contexto": {"circuito": "C1"},
        "escenarios": [{"nombre": "A", "criterio": "x", "top_variables": list(range(10)), "modos": list(range(10))}],
        "graph_html_paths": [{"escenario": "periodo completo"}, {"escenario": "puntos criticos"}],
    }

    result = compact_inference_context(context)

    assert result["contexto"] == {"circuito": "C1"}
    assert result["escenarios"][0]["top_variables"] == [0, 1, 2, 3, 4]
    assert result["graph_sections_requeridas"] == ["periodo_completo", "puntos_criticos"]
    assert "SOLO JSON" in build_inference_regeneration_prompt(context)


def test_compact_expert_alignment_context_limits_large_lists():
    context = {"pdf_expert_matches": list(range(10)), "variables_modelo_predictivo": list(range(100))}

    result = compact_expert_alignment_context(context)

    assert result["pdf_expert_matches"] == [0, 1, 2, 3, 4, 5]
    assert len(result["variables_modelo_predictivo"]) == 80


def test_variables_from_inference_extracts_unique_names():
    context = {"escenarios": [{"top_variables": [{"variable": "A"}, "B", {"variable": "A"}]}]}

    assert variables_from_inference(context) == ["A", "B"]


def test_auto_simulator_validation_and_prompt():
    valid = '{"titulo":"t","resumen":[],"variables_mas_sensibles":[],"patrones_minimo_maximo":[],"hallazgos_para_criticidad":[],"limitaciones":[],"contexto_reutilizado":[]}'

    assert validate_auto_simulator_response(valid)["ok"] is True
    assert validate_auto_simulator_response("{}")["ok"] is False
    assert "Contexto compacto" in build_auto_simulator_prompt("skills", {"a": 1}, errors=["x"])


def test_compact_auto_simulation_context_limits_table_and_scenarios():
    df = pd.DataFrame({"variable": list(range(25))})
    inference_context = {"escenarios": [{"nombre": str(i), "top_variables": [1, 2, 3, 4, 5], "modos": [1, 2, 3, 4]} for i in range(6)]}

    result = compact_auto_simulation_context(
        automatic_simulation_results_df=df,
        automatic_simulation_metadata={"warnings": []},
        automatic_simulation_cost_context={"disponible": False},
        automatic_simulation_softmax_curves={"variables": []},
        variables_priorizadas=list("ABCDE"),
        variables_bajo_analisis=list("ABCDEFG"),
        inference_context_package=inference_context,
        circuito="C1",
        fecha_inicio="2026-01-01",
        fecha_fin="2026-02-01",
        model_name="Model",
    )

    assert len(result["tabla_simulador_automatico"]) == 20
    assert len(result["contexto_inferencia_resumen"]["escenarios"]) == 4
