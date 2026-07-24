"""Tests for `chec_local_interpreter.circuit_meta_graph` -- the standalone
module that builds a fixed-position radial ("circular") meta-graph of sampled
circuits and cross-circuit patterns, sourced SOLELY from
`graph-patterns.<grupo>.<win>.json` (design D1/D2/D3: PR1 of the
`informe-gerencial-circular-graph` change).

This module has ZERO dependency on `informe_gerencial_contract.py`'s report
rendering -- it only reuses `load_graph_patterns` (pure I/O) from there for
the single-sourced min-support/circuitos filtering.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

import chec_local_interpreter.circuit_meta_graph as circuit_meta_graph
from chec_local_interpreter.circuit_meta_graph import (
    CircularGraphOutcome,
    _build_graph_elements,
    _render_html,
    build_circuit_meta_graph,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_graph_patterns_json(path: Path, patterns: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "informe-gerencial-graph-patterns/v1",
                "query": "temas recurrentes",
                "min_support": 2,
                "patterns": patterns,
            }
        ),
        encoding="utf-8",
    )


# Canonical identities sort in the SAME order as these raw strings, so the
# outer-ring angle assignment is predictable: AAA -> 0, BBB -> pi/2 (4-circuit
# ring), CCC -> pi, DDD -> 3pi/2.
CIRCUIT_A = "AAA23L01"
CIRCUIT_B = "BBB23L02"
CIRCUIT_C = "CCC23L03"
CIRCUIT_D = "DDD23L04"


# ---------------------------------------------------------------------------
# Phase 1, tasks 1.1/1.2: meta-graph data model (`_build_graph_elements`)
# ---------------------------------------------------------------------------


def test_build_graph_elements_two_circuits_share_pattern():
    """Spec scenario "Two circuits share a pattern": nodes A, B, and the
    pattern exist with edges A-pattern, B-pattern, and one circuit-to-circuit
    edge A-B.
    """
    patterns = [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]

    nodes, edges = _build_graph_elements(patterns, max_patterns=None)

    circuit_nodes = [n for n in nodes if n["kind"] == "circuit"]
    pattern_nodes = [n for n in nodes if n["kind"] == "pattern"]
    assert {n["label"] for n in circuit_nodes} == {CIRCUIT_A, CIRCUIT_B}
    assert len(pattern_nodes) == 1
    assert pattern_nodes[0]["label"] == "fauna en vanos"

    circuit_pattern_edges = [e for e in edges if e["kind"] == "circuit_pattern"]
    circuit_circuit_edges = [e for e in edges if e["kind"] == "circuit_circuit"]
    assert len(circuit_pattern_edges) == 2
    assert len(circuit_circuit_edges) == 1
    assert circuit_circuit_edges[0]["weight"] == 1


def test_build_graph_elements_circuit_circuit_weight_is_shared_pattern_count():
    """Two patterns both connecting A and B -> circuit-to-circuit edge weight
    equals the shared-pattern count (2), not the naive edge count.
    """
    patterns = [
        {"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "clima aislado", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
    ]

    nodes, edges = _build_graph_elements(patterns, max_patterns=None)

    pattern_nodes = [n for n in nodes if n["kind"] == "pattern"]
    circuit_circuit_edges = [e for e in edges if e["kind"] == "circuit_circuit"]
    assert len(pattern_nodes) == 2
    assert len(circuit_circuit_edges) == 1
    assert circuit_circuit_edges[0]["weight"] == 2


def test_build_graph_elements_one_node_per_circuit_and_per_pattern():
    patterns = [
        {"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "clima aislado", "circuitos": [CIRCUIT_B, CIRCUIT_C], "soporte": 2},
    ]

    nodes, edges = _build_graph_elements(patterns, max_patterns=None)

    circuit_nodes = [n for n in nodes if n["kind"] == "circuit"]
    pattern_nodes = [n for n in nodes if n["kind"] == "pattern"]
    # One node per circuit appearing in ANY pattern's circuitos (A, B, C).
    assert {n["label"] for n in circuit_nodes} == {CIRCUIT_A, CIRCUIT_B, CIRCUIT_C}
    # One node per pattern tema.
    assert {n["label"] for n in pattern_nodes} == {"fauna en vanos", "clima aislado"}
    # circuit-to-pattern edges MUST match membership exactly (2 patterns x 2
    # circuitos each = 4 membership edges).
    circuit_pattern_edges = [e for e in edges if e["kind"] == "circuit_pattern"]
    assert len(circuit_pattern_edges) == 4


# ---------------------------------------------------------------------------
# Phase 1, tasks 1.3/1.4: never-raise degrade guards (`build_circuit_meta_graph`)
# ---------------------------------------------------------------------------


def test_build_circuit_meta_graph_skipped_empty_too_few_sampled(tmp_path):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path, [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]
    )
    output_path = tmp_path / "graph-circular.html"

    outcome = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A], output_path)

    assert outcome.status == "skipped_empty"
    assert not output_path.exists()


def test_build_circuit_meta_graph_skipped_empty_no_patterns_meet_threshold(tmp_path):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [{"tema": "clima aislado", "circuitos": [CIRCUIT_A], "soporte": 1}],
    )
    output_path = tmp_path / "graph-circular.html"

    outcome = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A, CIRCUIT_B], output_path)

    assert outcome.status == "skipped_empty"
    assert not output_path.exists()


def test_build_circuit_meta_graph_skipped_empty_zero_patterns(tmp_path):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(graph_patterns_path, [])
    output_path = tmp_path / "graph-circular.html"

    outcome = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A, CIRCUIT_B], output_path)

    assert outcome.status == "skipped_empty"
    assert not output_path.exists()


def test_build_circuit_meta_graph_execution_error_missing_file_never_raises(tmp_path):
    missing_path = tmp_path / "does-not-exist.json"
    output_path = tmp_path / "graph-circular.html"

    outcome = build_circuit_meta_graph(missing_path, [CIRCUIT_A, CIRCUIT_B], output_path)

    assert outcome.status == "execution_error"
    assert outcome.errors
    assert not output_path.exists()


def test_build_circuit_meta_graph_execution_error_malformed_json_never_raises(tmp_path):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    graph_patterns_path.parent.mkdir(parents=True, exist_ok=True)
    graph_patterns_path.write_text("{not valid json::", encoding="utf-8")
    output_path = tmp_path / "graph-circular.html"

    outcome = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A, CIRCUIT_B], output_path)

    assert outcome.status == "execution_error"
    assert outcome.errors
    assert not output_path.exists()


def test_build_circuit_meta_graph_success_reports_node_and_edge_counts(tmp_path):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path, [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]
    )
    output_path = tmp_path / "graph-circular.html"

    outcome = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A, CIRCUIT_B], output_path)

    assert outcome.status == "success"
    assert outcome.output_path == str(output_path)
    assert outcome.node_count == 3  # 2 circuits + 1 pattern
    assert outcome.edge_count == 3  # 2 circuit-pattern + 1 circuit-circuit
    assert output_path.exists()


# ---------------------------------------------------------------------------
# Phase 1, tasks 1.5/1.6: deterministic radial layout
# ---------------------------------------------------------------------------


def test_build_graph_elements_alphabetical_ring_positions():
    """Outer ring ordered alphabetically by canonical_circuit_identity;
    angle theta_k = 2*pi*k/C, so with 4 circuits A/B/C/D the ring positions
    land at 0, pi/2, pi, 3pi/2 respectively.
    """
    patterns = [
        {"tema": "p1", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "p2", "circuitos": [CIRCUIT_C, CIRCUIT_D], "soporte": 2},
    ]

    nodes, _edges = _build_graph_elements(patterns, max_patterns=None)
    circuit_nodes = {n["label"]: n for n in nodes if n["kind"] == "circuit"}

    def angle_of(node: dict[str, Any]) -> float:
        return math.atan2(node["y"], node["x"]) % (2 * math.pi)

    assert angle_of(circuit_nodes[CIRCUIT_A]) == pytest.approx(0.0, abs=1e-6)
    assert angle_of(circuit_nodes[CIRCUIT_B]) == pytest.approx(math.pi / 2, abs=1e-6)
    assert angle_of(circuit_nodes[CIRCUIT_C]) == pytest.approx(math.pi, abs=1e-6)
    assert angle_of(circuit_nodes[CIRCUIT_D]) == pytest.approx(3 * math.pi / 2, abs=1e-6)


def test_build_graph_elements_pattern_inner_angle_is_circular_mean():
    """A pattern's inner angle is the circular mean of its member circuits'
    outer-ring angles -- NOT their arithmetic mean (which would be wrong on a
    circle). With the 4-circuit ring (A at 0, B at pi/2), the pattern
    connecting only A and B lands at their circular mean, pi/4. A second
    (unrelated) pattern brings C/D into the ring so it has 4 members, exactly
    like `test_build_graph_elements_alphabetical_ring_positions`.
    """
    patterns = [
        {"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "clima aislado", "circuitos": [CIRCUIT_C, CIRCUIT_D], "soporte": 2},
    ]

    nodes, _edges = _build_graph_elements(patterns, max_patterns=None)
    pattern_node = next(n for n in nodes if n["label"] == "fauna en vanos")

    angle = math.atan2(pattern_node["y"], pattern_node["x"]) % (2 * math.pi)
    assert angle == pytest.approx(math.pi / 4, abs=1e-6)


def test_build_graph_elements_inner_radius_strictly_less_than_outer_radius():
    patterns = [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]

    nodes, _edges = _build_graph_elements(patterns, max_patterns=None)
    circuit_radius = next(math.hypot(n["x"], n["y"]) for n in nodes if n["kind"] == "circuit")
    pattern_radius = next(math.hypot(n["x"], n["y"]) for n in nodes if n["kind"] == "pattern")

    assert pattern_radius < circuit_radius


def test_build_graph_elements_stable_positions_across_repeated_builds():
    patterns = [
        {"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "clima aislado", "circuitos": [CIRCUIT_B, CIRCUIT_C], "soporte": 2},
    ]

    nodes_1, edges_1 = _build_graph_elements(patterns, max_patterns=None)
    nodes_2, edges_2 = _build_graph_elements(patterns, max_patterns=None)

    assert nodes_1 == nodes_2
    assert edges_1 == edges_2


def test_build_circuit_meta_graph_identical_positions_across_two_builds(tmp_path):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path,
        [
            {"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
            {"tema": "clima aislado", "circuitos": [CIRCUIT_B, CIRCUIT_C], "soporte": 2},
        ],
    )
    # Same output FILENAME in two separate directories -- "identical input"
    # includes the output name (embedded in the HTML <title>), so only the
    # directory differs between the two builds.
    output_path_1 = tmp_path / "run-1" / "graph-circular.html"
    output_path_2 = tmp_path / "run-2" / "graph-circular.html"

    outcome_1 = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A, CIRCUIT_B, CIRCUIT_C], output_path_1)
    outcome_2 = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A, CIRCUIT_B, CIRCUIT_C], output_path_2)

    assert outcome_1.status == outcome_2.status == "success"
    assert output_path_1.read_text(encoding="utf-8") == output_path_2.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 1, tasks 1.7/1.8: max_patterns cap + hub dedup
# ---------------------------------------------------------------------------


def test_build_graph_elements_max_patterns_caps_to_top_n_by_soporte():
    patterns = [
        {"tema": "p-low", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "p-mid", "circuitos": [CIRCUIT_B, CIRCUIT_C], "soporte": 3},
        {"tema": "p-high", "circuitos": [CIRCUIT_C, CIRCUIT_D], "soporte": 4},
    ]

    nodes, _edges = _build_graph_elements(patterns, max_patterns=2)

    pattern_labels = {n["label"] for n in nodes if n["kind"] == "pattern"}
    assert pattern_labels == {"p-high", "p-mid"}


def test_build_graph_elements_max_patterns_tie_break_alphabetical_by_tema():
    patterns = [
        {"tema": "z-tema", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "a-tema", "circuitos": [CIRCUIT_B, CIRCUIT_C], "soporte": 2},
        {"tema": "m-tema", "circuitos": [CIRCUIT_C, CIRCUIT_D], "soporte": 2},
    ]

    nodes, _edges = _build_graph_elements(patterns, max_patterns=1)

    pattern_labels = {n["label"] for n in nodes if n["kind"] == "pattern"}
    assert pattern_labels == {"a-tema"}


def test_build_graph_elements_hub_pattern_renders_as_single_node():
    """Spec scenario "Hub pattern connects every sampled circuit": exactly
    one pattern node with exactly len(sampled) circuit-to-pattern edges --
    never duplicated.
    """
    sampled_circuits = [CIRCUIT_A, CIRCUIT_B, CIRCUIT_C, CIRCUIT_D]
    patterns = [{"tema": "hub-tema", "circuitos": sampled_circuits, "soporte": 4}]

    nodes, edges = _build_graph_elements(patterns, max_patterns=None)

    pattern_nodes = [n for n in nodes if n["kind"] == "pattern"]
    assert len(pattern_nodes) == 1
    circuit_pattern_edges = [e for e in edges if e["kind"] == "circuit_pattern"]
    assert len(circuit_pattern_edges) == len(sampled_circuits)


def test_build_circuit_meta_graph_default_max_patterns_is_reasonable(tmp_path):
    """Task 1.9: validate the default `max_patterns` (~24) does not silently
    drop patterns for a realistically-sized sample (well below the ceiling).
    """
    patterns = [
        {"tema": f"tema-{i}", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2} for i in range(10)
    ]
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(graph_patterns_path, patterns)
    output_path = tmp_path / "graph-circular.html"

    outcome = build_circuit_meta_graph(graph_patterns_path, [CIRCUIT_A, CIRCUIT_B], output_path)

    assert outcome.status == "success"
    assert outcome.node_count == 2 + 10  # every pattern retained, below default ceiling


# ---------------------------------------------------------------------------
# Phase 2, tasks 2.1/2.2: radial HTML renderer (`_render_html`)
# ---------------------------------------------------------------------------


def test_render_html_disables_physics_and_fixes_node_positions():
    patterns = [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]
    nodes, edges = _build_graph_elements(patterns, max_patterns=None)

    html = _render_html(nodes, edges, output_name="graph-circular.html")

    # Physics MUST be disabled at export (spec: "Radial Layout").
    assert '"physics": false' in html
    # Every node MUST have its x/y fixed (design D1 -- graphify's own
    # `to_html` exposes no such hook).
    assert '"fixed": {"x": true, "y": true}' in html
    assert '"x":' in html and '"y":' in html
    assert "vis.Network" in html


def test_render_html_byte_identical_for_identical_input():
    patterns = [
        {"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "clima aislado", "circuitos": [CIRCUIT_B, CIRCUIT_C], "soporte": 2},
    ]
    nodes, edges = _build_graph_elements(patterns, max_patterns=None)

    html_1 = _render_html(nodes, edges, output_name="graph-circular.html")
    html_2 = _render_html(nodes, edges, output_name="graph-circular.html")

    assert html_1 == html_2


def test_render_html_embeds_every_node_id_and_edge():
    patterns = [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]
    nodes, edges = _build_graph_elements(patterns, max_patterns=None)

    html = _render_html(nodes, edges, output_name="graph-circular.html")

    for node in nodes:
        assert json.dumps(node["id"]) in html
    assert len(edges) == 3  # 2 circuit-pattern + 1 circuit-circuit -- sanity on fixture


# ---------------------------------------------------------------------------
# Phase 3, tasks 3.1/3.2: `circuit_meta_graph build` CLI
# ---------------------------------------------------------------------------


def test_cli_build_exit_zero_on_success(tmp_path, capsys):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path, [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]
    )
    output_path = tmp_path / "graph-circular.html"

    exit_code = circuit_meta_graph.main(
        [
            "build",
            "--graph-patterns",
            str(graph_patterns_path),
            "--output",
            str(output_path),
            "--sampled",
            CIRCUIT_A,
            CIRCUIT_B,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert output_path.exists()


def test_cli_build_exit_zero_on_skipped_empty(tmp_path, capsys):
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(
        graph_patterns_path, [{"tema": "fauna en vanos", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2}]
    )
    output_path = tmp_path / "graph-circular.html"

    exit_code = circuit_meta_graph.main(
        [
            "build",
            "--graph-patterns",
            str(graph_patterns_path),
            "--output",
            str(output_path),
            "--sampled",
            CIRCUIT_A,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped_empty"
    assert not output_path.exists()


def test_cli_build_exit_two_on_execution_error(tmp_path, capsys):
    graph_patterns_path = tmp_path / "does-not-exist.json"
    output_path = tmp_path / "graph-circular.html"

    exit_code = circuit_meta_graph.main(
        [
            "build",
            "--graph-patterns",
            str(graph_patterns_path),
            "--output",
            str(output_path),
            "--sampled",
            CIRCUIT_A,
            CIRCUIT_B,
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "execution_error"


def test_cli_build_respects_max_patterns_flag(tmp_path, capsys):
    patterns = [
        {"tema": "p-low", "circuitos": [CIRCUIT_A, CIRCUIT_B], "soporte": 2},
        {"tema": "p-high", "circuitos": [CIRCUIT_B, CIRCUIT_C], "soporte": 3},
    ]
    graph_patterns_path = tmp_path / "graph-patterns.json"
    _write_graph_patterns_json(graph_patterns_path, patterns)
    output_path = tmp_path / "graph-circular.html"

    exit_code = circuit_meta_graph.main(
        [
            "build",
            "--graph-patterns",
            str(graph_patterns_path),
            "--output",
            str(output_path),
            "--sampled",
            CIRCUIT_A,
            CIRCUIT_B,
            CIRCUIT_C,
            "--max-patterns",
            "1",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    # Only p-high (circuitos=[B, C]) survives the cap, so circuit A -- which
    # appeared ONLY in the capped-out p-low -- is never materialized as a
    # node: 2 circuits (B, C) + 1 pattern node.
    assert payload["node_count"] == 3
