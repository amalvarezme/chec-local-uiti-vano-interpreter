from __future__ import annotations

import json

from chec_impacto.interpretability.circuit_analysis import validar_respuesta_inferencia
from chec_local_interpreter.inference_validation import (
    allowed_ventanas,
    errores_de_metrica,
)


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


# --- El modelo predice UITI, no frecuencia ------------------------------------------------


def _contexto_mil():
    return {
        "circuito_interes": "C1",
        "modelo_tipo": "mil_bolsas",
        "unidad": "bolsa (vano, ventana)",
        "metrica": "uiti_acumulado",
        "fecha_inicio": "2026-01-01",
        "fecha_fin": "2026-03-01",
        "fechas_interes": [],
        "features": ["NR_T"],
        "ventanas": ["V1", "V2"],
        "escenarios": [{"nombre": "C1 -- ventana V1", "ventana": "V1"}],
    }


def test_the_agent_may_not_attribute_event_frequency_to_the_model():
    """El MIL predice UITI acumulado. El conteo de eventos es un EJE del espacio
    KMeans que fija la clase, no una salida del modelo.

    Sin esta guarda el agente escribe "el modelo indica que esta variable aumenta la
    FRECUENCIA de eventos" -- una frase plausible, imposible de distinguir de una
    correcta al leer el informe, y que el modelo no respalda. Es justo el tipo de
    afirmacion que un validador puede atrapar y un lector no.
    """
    errores = errores_de_metrica(
        {"hallazgos": ["El modelo muestra que NR_T eleva la frecuencia de eventos."]},
        _contexto_mil(),
    )

    assert errores, "atribuir frecuencia al modelo tiene que ser un error"
    assert any("uiti" in e.lower() for e in errores)


def test_describing_event_counts_as_observed_data_is_allowed():
    """La frecuencia sigue siendo un dato del caso. Lo prohibido es colgarsela al
    MODELO, no mencionarla: el historiador la reporta y el agente puede citarla como
    contexto observado."""
    errores = errores_de_metrica(
        {"contexto": "El circuito registro 14 eventos observados en la ventana V1."},
        _contexto_mil(),
    )

    assert errores == []


def test_windows_are_part_of_the_citable_universe():
    """El escenario ahora ES una ventana. Sin declararlas, el agente no puede nombrar
    la ventana de la que habla sin salirse del universo permitido."""
    assert allowed_ventanas(_contexto_mil()) == {"V1", "V2"}
