from __future__ import annotations

from chec_impacto.data.graph_visualization import (
    build_edges,
    build_preserved_edges,
    create_graph,
    expand_variables,
    selected_variables,
)


def sample_config():
    return {
        "ventanaClimaticaHoras": 3,
        "modos": [
            {"id": "A", "nombre": "Eventos", "variables": ["COD_CAUSA"], "cantidad": 1},
            {
                "id": "F",
                "nombre": "Clima",
                "variablesEstaticas": ["NR_T", "DDT"],
                "familiasClimaticas": ["prep", "temp"],
                "cantidad": 8,
            },
        ],
    }


def test_expand_and_select_variables_by_climate_family():
    variables_by_mode, climate_families = expand_variables(sample_config())

    assert variables_by_mode["F"] == ["NR_T", "DDT", "prep_0", "prep_1", "prep_2", "temp_0", "temp_1", "temp_2"]
    assert climate_families == {"prep", "temp"}

    selected = selected_variables(variables_by_mode, {"COD_CAUSA", "prep"}, climate_families)

    assert selected["A"] == ["COD_CAUSA"]
    assert selected["F"] == ["prep_0", "prep_1", "prep_2"]


def test_build_edges_adds_lag_edges_and_static_domain_edges():
    edges = build_edges(sample_config())

    assert ("prep_2", "prep_1", 0.90) in edges
    assert ("prep_0", "COD_CAUSA", 0.85) in edges
    assert ("NR_T", "COD_CAUSA", 0.85) in edges
    assert ("DDT", "COD_CAUSA", 0.90) in edges


def test_build_preserved_edges_keeps_direct_and_virtual_paths():
    edges = [("A", "B", 0.8), ("B", "C", 0.6), ("A", "C", 0.5)]

    result = build_preserved_edges(edges, {"A", "C"})

    assert {edge["is_virtual"] for edge in result} == {False}
    assert result[0]["source"] == "A"
    assert result[0]["target"] == "C"
    assert result[0]["weight"] == 0.5


def test_build_preserved_edges_creates_virtual_path_when_direct_missing():
    edges = [("A", "B", 0.8), ("B", "C", 0.6)]

    result = build_preserved_edges(edges, {"A", "C"})

    assert result == [
        {"source": "A", "target": "C", "weight": 0.6, "path": ["A", "B", "C"], "is_virtual": True}
    ]


def test_create_graph_marks_preserved_virtual_edges():
    graph = create_graph(
        {"A": ["A"], "B": ["C"]},
        [("A", "B", 0.8), ("B", "C", 0.6)],
        {"A": "Mode A", "B": "Mode B"},
        mode_colors={"A": "red", "B": "blue"},
        preserve_filtered_connections=True,
    )

    assert graph.number_of_nodes() == 2
    assert graph.has_edge("A", "C")
    assert graph.edges["A", "C"]["dashes"] is True
