from __future__ import annotations

import json

from chec_impacto.interpretability.circuit_analysis import validar_respuesta_inferencia


def test_inference_validation_accepts_graph_discussion_dict_and_normalizes():
    context = {
        "graph_html_paths": [
            {"escenario": "Top P97 por UITI_VANO — período completo", "path": "top_uiti_periodo.html"},
            {"escenario": "Top P97 por frecuencia — puntos críticos", "path": "top_frecuencia_fechas.html"},
        ],
        "escenarios": [
            {"nombre": "Top P97 por UITI_VANO — período completo"},
            {"nombre": "Top P97 por frecuencia — puntos críticos"},
        ],
    }
    response = {
        "escenarios": [
            {"nombre": "Top P97 por UITI_VANO — período completo", "interpretacion": "Periodo."},
            {"nombre": "Top P97 por frecuencia — puntos críticos", "interpretacion": "Criticos."},
        ],
        "discusion_grafos": {
            "periodo_completo": "Lectura de asociaciones relativas del periodo completo.",
            "puntos_criticos": "Lectura de asociaciones relativas de puntos criticos.",
        },
    }

    result = validar_respuesta_inferencia(json.dumps(response, ensure_ascii=False), context)

    assert result["ok"] is True
    assert result["data"]["discusion_grafos"] == [
        {"seccion": "periodo_completo", "lectura": "Lectura de asociaciones relativas del periodo completo."},
        {"seccion": "puntos_criticos", "lectura": "Lectura de asociaciones relativas de puntos criticos."},
    ]
