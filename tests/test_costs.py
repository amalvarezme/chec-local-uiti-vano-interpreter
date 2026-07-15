from __future__ import annotations

import pandas as pd

from chec_local_interpreter.costs import build_auto_simulation_cost_context, find_cost_matches, load_cost_items


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


def test_build_auto_simulation_cost_context_degrades_when_no_cost_matches():
    simulation = pd.DataFrame([{"variable": "VARIABLE_SIN_RELACION", "magnitud_max_cambio_abs": 0.8}])
    costs = pd.DataFrame([{"item": "PODA EN REDES RURALES TIPO A", "costo_promedio": 166112.0}])

    context = build_auto_simulation_cost_context(simulation, costs)

    assert context["disponible"] is False
    assert context["coincidencias"] == []
    assert "No se encontraron ítems de costo cercanos" in context["advertencias"][0]


def test_find_cost_matches_keeps_missing_numeric_cost_as_reference():
    costs = pd.DataFrame([{"item": "SERVICIO DE INSTALACION DE TRANSFORMADOR", "costo_promedio": None}])

    matches = find_cost_matches("CNT_TRF transformador", costs)

    assert matches[0]["item_costo"] == "SERVICIO DE INSTALACION DE TRANSFORMADOR"
    assert matches[0]["costo_promedio"] is None


def test_load_cost_items_accepts_expected_excel_headers(tmp_path):
    workbook = tmp_path / "costos.xlsx"
    pd.DataFrame(
        [{"Etiquetas de fila": "SERVICIO DE PODA", "Promedio de UNITCOST": "12345"}]
    ).to_excel(workbook, index=False)

    loaded = load_cost_items(workbook)

    assert loaded.to_dict(orient="records") == [
        {"item": "SERVICIO DE PODA", "costo_promedio": 12345}
    ]
