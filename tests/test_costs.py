from __future__ import annotations

import pandas as pd

from chec_local_interpreter.costs import build_auto_simulation_cost_context, find_cost_matches


def test_find_cost_matches_uses_domain_keywords_for_variable():
    costs = pd.DataFrame(
        [
            {"item": "SERVICIO DE INSTALACION DE TRANSFORMADOR MONOFASICO", "costo_promedio": 674795.0},
            {"item": "PODA EN REDES RURALES TIPO A", "costo_promedio": 166112.0},
        ]
    )

    matches = find_cost_matches("CNT_TRF transformador bajantes", costs)

    assert matches[0]["item_costo"] == "SERVICIO DE INSTALACION DE TRANSFORMADOR MONOFASICO"
    assert matches[0]["costo_promedio"] == 674795.0
    assert matches[0]["puntaje_cercania"] > 0


def test_build_auto_simulation_cost_context_returns_matches_by_sensitive_variable():
    simulation = pd.DataFrame(
        [
            {
                "variable": "CNT_TRF",
                "magnitud_max_cambio_abs": 0.35,
                "riesgo_base_etiqueta": "Riesgo bajo",
                "riesgo_valor_minimo_etiqueta": "Riesgo bajo",
                "riesgo_valor_maximo_etiqueta": "Riesgo alto",
            }
        ]
    )
    costs = pd.DataFrame(
        [{"item": "SERVICIO DE INSTALACION DE TRANSFORMADOR TRIFASICO", "costo_promedio": 696655.0}]
    )

    context = build_auto_simulation_cost_context(simulation, costs)

    assert context["disponible"] is True
    assert context["coincidencias"][0]["variable"] == "CNT_TRF"
    assert context["coincidencias"][0]["items_costo_cercanos"][0]["costo_promedio"] == 696655.0
