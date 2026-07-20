"""Tests for `chec_local_interpreter.graph_view_builder` -- the sole module in
this feature allowed to import/call `graphify.export.to_html` directly (design
D4/D2: "informe-gerencial-vault-graph-embed"). Builds a circuit-scoped
sub-graph (seed + bridge predicate) from the shared `graphify-out/graph.json`
and exports it to a standalone HTML figure, never raising regardless of
malformed/oversize input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import chec_local_interpreter.graph_view_builder as graph_view_builder
from chec_local_interpreter.graph_view_builder import GraphViewOutcome, build_graph_view

# ---------------------------------------------------------------------------
# Phase 2: realistic graph.json-shaped fixtures
# ---------------------------------------------------------------------------


def _node(
    node_id: str,
    *,
    source_file: str | None = None,
    source_location: str | None = None,
    community: int | None,
    label: str = "node",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "file_type": "code",
        "type": "FUNCTION",
        "source_file": source_file,
        "source_location": source_location,
        "complexity": 1,
        "loc": 1,
        "level": 1,
        "granularity": "low",
        "heat": 0.05,
        "owner": "unowned",
        "community": community,
        "norm_label": label,
    }


def _link(source: str, target: str) -> dict[str, Any]:
    return {
        "relation": "contains",
        "confidence": "EXTRACTED",
        "weight": 1.0,
        "confidence_score": 1.0,
        "source": source,
        "target": target,
    }


def realistic_graph_json_fixture() -> dict[str, Any]:
    """A node-link dict modeled on the real `graphify-out/graph.json` shape
    (`nodes`/`links` keys, `source_file`/`source_location`/`community`
    per-node attributes across >=2 sampled circuits), used to exercise the
    seed/bridge predicate (design D2) realistically -- not a trivial toy
    graph that would under-test it.

    Sampled circuits for these tests: CHA23L14, DON23L13. HER23L16 is
    deliberately NOT sampled, to exercise exclusion of an unrelated circuit's
    nodes even when they carry edges into the graph.
    """
    nodes = [
        _node("cha_seed_1", source_file="reports/vault/CHA23L14.md", community=1, label="cha seed 1"),
        _node("cha_seed_2", source_file="reports/vault/CHA23L14.md", community=1, label="cha seed 2"),
        _node("don_seed_1", source_file="reports/vault/DON23L13.md", community=2, label="don seed 1"),
        _node("don_seed_2", source_file="reports/vault/DON23L13.md", community=2, label="don seed 2"),
        # Seed node reached ONLY via `source_location` fallback (no `source_file`)
        # -- exercises the fallback branch of the provenance predicate (design D2).
        _node("cha_fallback", source_file=None, source_location="reports/vault/CHA23L14.md", community=1, label="cha fallback"),
        # Bridge candidate with 2 DISTINCT seed neighbors (cha_seed_1, don_seed_1)
        # -> retained as a bridge node.
        _node("bridge_strong", source_file="llm/evals/run_llm_eval.py", community=3, label="bridge strong"),
        # Bridge candidate with only 1 seed neighbor -> excluded.
        _node("bridge_weak", source_file="llm/evals/other_module.py", community=3, label="bridge weak"),
        # Retained bridge node (2 distinct seed neighbors) whose own provenance
        # (a non-vault-note file) resolves to no single sampled circuit --
        # exercises the "Vinculos compartidos" shared-bucket fallback in
        # `_circuit_communities`, regardless of its (now-unused-for-grouping)
        # `community` attribute.
        _node("no_community_bridge", source_file="llm/evals/uncommunitied.py", community=None, label="no community bridge"),
        # Node from an UNSAMPLED circuit -- must be excluded entirely, even
        # though it carries an edge (to bridge_weak, itself excluded).
        _node("her_unsampled", source_file="reports/vault/HER23L16.md", community=4, label="her unsampled"),
    ]
    links = [
        _link("cha_seed_1", "bridge_strong"),
        _link("don_seed_1", "bridge_strong"),
        _link("cha_seed_2", "bridge_weak"),
        _link("cha_seed_1", "cha_seed_2"),
        _link("cha_fallback", "don_seed_2"),
        _link("no_community_bridge", "cha_seed_1"),
        _link("no_community_bridge", "don_seed_1"),
        _link("her_unsampled", "bridge_weak"),
    ]
    return {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": nodes,
        "links": links,
    }


def _write_graph_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def malformed_graph_json_fixture() -> dict[str, Any]:
    """Missing the `nodes`/`links` keys entirely -- exercises the
    `execution_error` path when `node_link_graph` cannot parse the shape.
    """
    return {"directed": False, "multigraph": False, "graph": {}}


def oversize_graph_json_fixture(n: int = 50) -> dict[str, Any]:
    """A large synthetic node count (still realistically shaped) used to
    exercise the `node_limit` auto-aggregation path without needing the full
    real-shaped fixture.
    """
    nodes = [
        _node(f"cha_seed_{i}", source_file="reports/vault/CHA23L14.md", community=1, label=f"cha {i}")
        for i in range(n // 2)
    ] + [
        _node(f"don_seed_{i}", source_file="reports/vault/DON23L13.md", community=2, label=f"don {i}")
        for i in range(n // 2)
    ]
    links = [_link(f"cha_seed_{i}", f"don_seed_{i}") for i in range(n // 2)]
    return {"directed": False, "multigraph": False, "graph": {}, "nodes": nodes, "links": links}


SAMPLED = ["CHA23L14", "DON23L13"]


# ---------------------------------------------------------------------------
# Phase 3: build_graph_view core (RED -> GREEN -> VERIFY)
# ---------------------------------------------------------------------------


def test_build_graph_view_seed_matches_provenance(tmp_path, monkeypatch):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    captured: dict[str, Any] = {}

    def _fake_to_html(G, communities, output, **kwargs):
        captured["nodes"] = set(G.nodes())
        Path(output).write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(graph_view_builder, "to_html", _fake_to_html)

    outcome = build_graph_view(graph_json_path, SAMPLED, output_path)

    assert outcome.status == "success"
    # Seed nodes (matched via source_file OR source_location fallback) are
    # all present in the retained node set.
    assert {"cha_seed_1", "cha_seed_2", "don_seed_1", "don_seed_2", "cha_fallback"} <= captured["nodes"]
    # The unsampled circuit's own node is never retained.
    assert "her_unsampled" not in captured["nodes"]


def test_build_graph_view_bridge_requires_two_seed_neighbors(tmp_path, monkeypatch):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    captured: dict[str, Any] = {}

    def _fake_to_html(G, communities, output, **kwargs):
        captured["nodes"] = set(G.nodes())
        Path(output).write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(graph_view_builder, "to_html", _fake_to_html)

    outcome = build_graph_view(graph_json_path, SAMPLED, output_path)

    assert outcome.status == "success"
    # bridge_strong has 2 DISTINCT seed neighbors (cha_seed_1, don_seed_1) ->
    # retained.
    assert "bridge_strong" in captured["nodes"]
    # bridge_weak has only 1 seed neighbor (cha_seed_2) -> excluded.
    assert "bridge_weak" not in captured["nodes"]
    assert outcome.node_count == len(captured["nodes"])


def test_build_graph_view_communities_grouped_by_circuit(tmp_path, monkeypatch):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    captured: dict[str, Any] = {}

    def _fake_to_html(G, communities, output, **kwargs):
        captured["nodes"] = set(G.nodes())
        captured["communities"] = communities
        captured["community_labels"] = kwargs.get("community_labels")
        Path(output).write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(graph_view_builder, "to_html", _fake_to_html)

    build_graph_view(graph_json_path, SAMPLED, output_path)

    communities = captured["communities"]
    # Community ids follow SAMPLED's order: CHA23L14 -> 0, DON23L13 -> 1.
    # Community 0 groups both cha seed nodes AND the fallback-matched node.
    assert set(communities[0]) == {"cha_seed_1", "cha_seed_2", "cha_fallback"}
    assert set(communities[1]) == {"don_seed_1", "don_seed_2"}
    # bridge_strong and no_community_bridge are retained (>=2 distinct seed
    # neighbors) but neither has provenance matching a single sampled
    # circuit -- both land in the trailing shared community (id == len(SAMPLED)).
    shared_cid = len(SAMPLED)
    assert set(communities[shared_cid]) == {"bridge_strong", "no_community_bridge"}
    # Every retained node is grouped into exactly one community -- none left
    # ungrouped (an ungrouped node would default to community 0's color in
    # `graphify.export.to_html`, misattributing it to the first circuit).
    all_grouped_nodes = {node for members in communities.values() for node in members}
    assert all_grouped_nodes == captured["nodes"]

    # community_labels names each circuit community by the circuit itself,
    # and the shared bucket by its own label -- this is what populates the
    # exported HTML's "Communities" panel checkboxes.
    assert captured["community_labels"] == {
        0: "CHA23L14",
        1: "DON23L13",
        shared_cid: "Vinculos compartidos",
    }


def test_build_graph_view_no_shared_bucket_when_no_bridge_nodes(tmp_path, monkeypatch):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(
        graph_json_path,
        {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [
                _node("cha_only", source_file="reports/vault/CHA23L14.md", community=1, label="cha only"),
                _node("don_only", source_file="reports/vault/DON23L13.md", community=2, label="don only"),
            ],
            "links": [_link("cha_only", "don_only")],
        },
    )
    output_path = tmp_path / "graph-view.html"

    captured: dict[str, Any] = {}

    def _fake_to_html(G, communities, output, **kwargs):
        captured["communities"] = communities
        captured["community_labels"] = kwargs.get("community_labels")
        Path(output).write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(graph_view_builder, "to_html", _fake_to_html)

    build_graph_view(graph_json_path, SAMPLED, output_path)

    # No bridge/off-circuit node was retained -- the shared bucket (id ==
    # len(SAMPLED)) must not appear at all, in `communities` or its labels.
    shared_cid = len(SAMPLED)
    assert shared_cid not in captured["communities"]
    assert captured["community_labels"] == {0: "CHA23L14", 1: "DON23L13"}


def test_build_graph_view_skipped_empty_too_few_sampled(tmp_path):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    outcome = build_graph_view(graph_json_path, ["CHA23L14"], output_path)

    assert outcome.status == "skipped_empty"
    assert not output_path.exists()


def test_build_graph_view_skipped_empty_no_matched_nodes(tmp_path):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    outcome = build_graph_view(graph_json_path, ["NOMATCH1", "NOMATCH2"], output_path)

    assert outcome.status == "skipped_empty"
    assert not output_path.exists()


def test_build_graph_view_execution_error_on_malformed_graph_never_raises(tmp_path):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, malformed_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    outcome = build_graph_view(graph_json_path, SAMPLED, output_path)

    assert outcome.status == "execution_error"
    assert outcome.errors


def test_build_graph_view_execution_error_when_to_html_raises_never_raises(tmp_path, monkeypatch):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    def _raising_to_html(*args, **kwargs):
        raise ValueError("graphify blew up")

    monkeypatch.setattr(graph_view_builder, "to_html", _raising_to_html)

    outcome = build_graph_view(graph_json_path, SAMPLED, output_path)

    assert outcome.status == "execution_error"
    assert any("graphify blew up" in err for err in outcome.errors)


def test_build_graph_view_node_limit_passed_through(tmp_path, monkeypatch):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, oversize_graph_json_fixture(n=40))
    output_path = tmp_path / "graph-view.html"

    captured: dict[str, Any] = {}

    def _fake_to_html(G, communities, output, **kwargs):
        captured["node_limit"] = kwargs.get("node_limit")
        Path(output).write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(graph_view_builder, "to_html", _fake_to_html)

    outcome = build_graph_view(graph_json_path, ["CHA23L14", "DON23L13"], output_path, node_limit=5)

    assert outcome.status == "success"
    assert captured["node_limit"] == 5


# ---------------------------------------------------------------------------
# CLI (task 3.7)
# ---------------------------------------------------------------------------


def test_cli_build_exit_zero_on_success(tmp_path, capsys, monkeypatch):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    def _fake_to_html(G, communities, output, **kwargs):
        Path(output).write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(graph_view_builder, "to_html", _fake_to_html)

    exit_code = graph_view_builder.main(
        [
            "build",
            "--graph-json",
            str(graph_json_path),
            "--output",
            str(output_path),
            "--sampled",
            "CHA23L14",
            "DON23L13",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"


def test_cli_build_exit_zero_on_skipped_empty(tmp_path, capsys):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, realistic_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    exit_code = graph_view_builder.main(
        [
            "build",
            "--graph-json",
            str(graph_json_path),
            "--output",
            str(output_path),
            "--sampled",
            "CHA23L14",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped_empty"


def test_cli_build_exit_two_on_execution_error(tmp_path, capsys):
    graph_json_path = tmp_path / "graph.json"
    _write_graph_json(graph_json_path, malformed_graph_json_fixture())
    output_path = tmp_path / "graph-view.html"

    exit_code = graph_view_builder.main(
        [
            "build",
            "--graph-json",
            str(graph_json_path),
            "--output",
            str(output_path),
            "--sampled",
            "CHA23L14",
            "DON23L13",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "execution_error"
