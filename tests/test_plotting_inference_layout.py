from __future__ import annotations

import pandas as pd

from chec_local_interpreter.plotting import render_expert_alignment_tab, render_llm_analysis


def test_inference_layout_consolidates_general_discussion(tmp_path):
    raw_df = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1"],
            "FECHA": ["2026-01-01", "2026-01-02"],
            "UITI_VANO": [10.0, 20.0],
            "FID_VANO": ["V1", "V2"],
        }
    )
    daily_df = pd.DataFrame(
        {
            "fecha_dia": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "UITI_VANO": [10.0, 20.0],
            "event_count": [1, 1],
        }
    )
    inference_results = {
        "top_frecuencia_periodo": {"contexto": {"nombre": "Frecuencia periodo"}},
        "top_uiti_periodo": {"contexto": {"nombre": "Severidad periodo"}},
        "top_frecuencia_puntos_criticos": {"contexto": {"nombre": "Frecuencia puntos"}},
        "top_uiti_puntos_criticos": {"contexto": {"nombre": "Severidad puntos"}},
    }
    inference_analysis = {
        "hallazgos": ["Hallazgo general uno.", "Hallazgo general dos."],
        "escenarios": [
            {"nombre": "Frecuencia periodo", "interpretacion": "Frecuencia item uno. Frecuencia item dos."},
            {"nombre": "Severidad periodo", "interpretacion": "Severidad item uno. Severidad item dos."},
            {"nombre": "Frecuencia puntos", "interpretacion": "Frecuencia critica uno. Frecuencia critica dos."},
            {"nombre": "Severidad puntos", "interpretacion": "Severidad critica uno. Severidad critica dos."},
        ],
        "discusion_grafos": [
            {"seccion": "periodo_completo", "lectura": "Grafo periodo uno."},
            {"seccion": "puntos_criticos", "lectura": "Grafo critico uno."},
        ],
        "hipotesis_modelo_predictivo": {
            "periodo_completo": [
                "El modelo sugiere que la recurrencia y la severidad del periodo se explican por señales combinadas de infraestructura y grafos."
            ],
            "puntos_criticos": [
                "El modelo sugiere que los puntos críticos concentran señales consistentes entre variables priorizadas y grafos estimados."
            ],
        },
    }

    html_path = render_llm_analysis(
        validation_data={},
        raw_df=raw_df,
        daily_df=daily_df,
        critical_points=[],
        selected_circuitos=["TODOS"],
        inference_results=inference_results,
        inference_analysis=inference_analysis,
        output_dir=tmp_path,
    )
    html = html_path.read_text(encoding="utf-8")

    assert html.count("Discusión general de inferencias del modelo") == 1
    assert "Hallazgos generales del modelo de inferencia" not in html
    assert "Discusión general de inferencias del modelo &mdash; Número de Eventos" not in html
    assert "<h4>Número de Eventos</h4>" in html
    assert "<h4>UITI_VANO</h4>" in html
    assert "Hipótesis del modelo predictivo — período completo" in html
    assert html.index("Hipótesis del modelo predictivo — período completo") > html.index("Discusión general de inferencias del modelo")
    assert "Hipótesis del modelo predictivo — puntos críticos" in html
    assert html.index("Hipótesis del modelo predictivo — puntos críticos") > html.index("Discusión de inferencias en puntos críticos")
    assert html.count("Discusión de inferencias en puntos críticos") == 1


def test_expert_alignment_tab_renders_auto_simulation_analysis():
    table = pd.DataFrame(
        [
            {
                "variable": "CNT_TRF",
                "valor_original_base": 1.0,
                "valor_minimo_usado": 0.0,
                "valor_maximo_usado": 3.0,
                "riesgo_base": 1.2,
                "riesgo_base_etiqueta": "Riesgo bajo",
                "riesgo_valor_minimo": 1.0,
                "riesgo_valor_minimo_etiqueta": "Riesgo bajo",
                "riesgo_valor_maximo": 1.5,
                "riesgo_valor_maximo_etiqueta": "Riesgo alto",
                "cambio_absoluto_minimo": -0.2,
                "cambio_absoluto_maximo": 0.3,
                "direccion_cambio_minimo": "disminuye riesgo",
                "direccion_cambio_maximo": "aumenta riesgo",
                "observacion": "CNT_TRF cambia el riesgo.",
            }
        ]
    )
    analysis = {
        "contexto": {"fuentes_usadas": ["Agente Descriptor", "Agente predictivo"]},
        "coincidencias": [],
        "diferencias": [],
        "variables_a_priorizar": [],
        "sintesis_final": "Síntesis.",
    }
    auto_analysis = {
        "resumen": ["Resumen del simulador."],
        "variables_mas_sensibles": [
            {"variable": "CNT_TRF", "lectura": "Mayor sensibilidad.", "mayor_cambio_abs": 0.3}
        ],
        "patrones_minimo_maximo": ["El mínimo baja y el máximo sube."],
        "hallazgos_para_criticidad": ["Útil para revisar criticidad."],
        "limitaciones": ["Una variable a la vez."],
        "contexto_reutilizado": ["Variables priorizadas."],
    }
    cost_context = {
        "disponible": True,
        "metodo": "Coincidencia por tokens.",
        "advertencias": [],
        "coincidencias": [
            {
                "variable": "CNT_TRF",
                "riesgo_base_etiqueta": "Riesgo bajo",
                "riesgo_valor_minimo_etiqueta": "Riesgo bajo",
                "riesgo_valor_maximo_etiqueta": "Riesgo alto",
                "items_costo_cercanos": [
                    {
                        "item_costo": "SERVICIO DE INSTALACION DE TRANSFORMADOR TRIFASICO",
                        "costo_promedio": 696655.0,
                        "puntaje_cercania": 0.42,
                    }
                ],
            }
        ],
    }

    html = render_expert_alignment_tab(
        analysis,
        automatic_simulation_table=table,
        automatic_simulation_analysis=auto_analysis,
        automatic_simulation_cost_context=cost_context,
    )

    assert "Análisis automático de sensibilidad" in html
    assert "CNT_TRF" in html
    assert "Cambio absoluto del riesgo por variable" in html
    assert "Riesgo bajo -&gt; Riesgo alto" in html
    assert "Costos aproximados por ítems de contrato" in html
    assert "SERVICIO DE INSTALACION DE TRANSFORMADOR TRIFASICO" in html
    assert "Mayor sensibilidad" in html
