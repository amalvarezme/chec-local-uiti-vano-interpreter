from __future__ import annotations

import pandas as pd

from chec_local_interpreter.plotting import render_llm_analysis


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
