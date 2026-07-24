"""Standalone builder for the "circular" cross-circuit meta-graph embedded in
the informe-gerencial managerial report (PR1 of the
`informe-gerencial-circular-graph` change).

Sibling of `graph_view_builder.py` -- NOT a modification of it -- so the
existing community/concept graph pipeline stays fully unchanged (design D1).
Aggregates `graph-patterns.<grupo>.<win>.json` (produced by the SKILL
runbook's step 2.5) into a two-node-type / two-edge-type meta-graph (circuit,
pattern) and hand-authors a fixed-position vis-network HTML export.

Design D1: `graphify.export.to_html` emits vis nodes with NO `x`/`y` and
hardcodes `physics: {enabled: true, solver: 'forceAtlas2Based'}` -- it
exposes no hook for fixed radial positions or `physics: false`. A fixed
radial layout is therefore impossible through it, so this module owns its
own HTML rendering (`_render_html`), reusing graphify's visual chrome idiom
(search box, info panel, legend) by hand rather than importing it.

Zero dependency on `informe_gerencial_contract.py`'s report rendering: only
`load_graph_patterns` (pure I/O, graphify-free) is reused from there, for the
single-sourced min-support/circuitos-intersection filtering -- this module
does not import anything else from that contract, and nothing there imports
this module yet (that wiring is PR2), so there is no circular dependency.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.informe_gerencial_contract import load_graph_patterns

SCHEMA_VERSION = "informe-gerencial-graph-circular/v1"

CircularGraphStatus = Literal["success", "skipped_empty", "execution_error"]

# Design D3: crowding cap -- keeps top-N inner (pattern) nodes by `soporte`,
# tie-break `tema` alphabetical. Mirrors `graph_view_builder.build_graph_view`'s
# existing `node_limit` parameter.
DEFAULT_MAX_PATTERNS = 24

_OUTER_RADIUS = 400.0
_INNER_RADIUS_BASE = 220.0
_INNER_RADIUS_STEP = 28.0
_INNER_RADIUS_FLOOR = 40.0
# Rounding precision used to bucket patterns that land on the SAME circular-
# mean angle (identical circuit membership), so they can be de-overlapped by
# a deterministic per-index radial offset (design D3) instead of drawing
# exactly on top of one another.
_ANGLE_BUCKET_PRECISION = 6


@dataclass(frozen=True)
class CircularGraphOutcome:
    """Mirrors `graph_view_builder.GraphViewOutcome`'s shape/conventions."""

    status: CircularGraphStatus
    output_path: str | None = None
    node_count: int = 0
    edge_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "output_path": self.output_path,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "errors": list(self.errors),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Pure data-model + layout functions (Phase 1)
# ---------------------------------------------------------------------------


def _cap_patterns(patterns: list[dict[str, Any]], max_patterns: int | None) -> list[dict[str, Any]]:
    """Deterministically cap `patterns` to the top-N by `soporte` descending,
    tie-break `tema` alphabetical (design D3). `None`/non-positive means "no
    cap".
    """
    if max_patterns is None or max_patterns <= 0 or len(patterns) <= max_patterns:
        return sorted(patterns, key=lambda p: (-int(p["soporte"]), str(p["tema"])))
    ordered = sorted(patterns, key=lambda p: (-int(p["soporte"]), str(p["tema"])))
    return ordered[:max_patterns]


def _circuit_angles(circuits: list[str]) -> dict[str, float]:
    """Outer ring: circuits ordered alphabetically by
    `canonical_circuit_identity` (design D3, NOT insertion/arg order), each
    placed at angle `theta_k = 2*pi*k/C` around the ring.
    """
    ordered = sorted(circuits, key=canonical_circuit_identity)
    count = len(ordered)
    return {circuit: (2 * math.pi * index / count) for index, circuit in enumerate(ordered)}


def _pattern_angle(member_circuits: Sequence[str], circuit_angles: dict[str, float]) -> float:
    """Circular mean of the member circuits' outer-ring angles (design D3) --
    the arithmetic mean of angles is wrong on a circle (e.g. averaging 350
    degrees and 10 degrees should yield 0, not 180).
    """
    xs = [math.cos(circuit_angles[c]) for c in member_circuits]
    ys = [math.sin(circuit_angles[c]) for c in member_circuits]
    return math.atan2(sum(ys) / len(ys), sum(xs) / len(xs))


def _build_graph_elements(
    patterns: list[dict[str, Any]],
    *,
    max_patterns: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the meta-graph's nodes/edges from an already-filtered `patterns`
    list (each entry shaped like `load_graph_patterns`'s output:
    `{"tema": str, "circuitos": list[str], "soporte": int}`).

    Pure function: deterministic node/edge lists (and layout positions) for
    the same input, every time -- no I/O, no side effects. Returns
    `(nodes, edges)`:
    - node: `{"id", "kind" ("circuit"|"pattern"), "label", "x", "y", "soporte"}`
    - edge: `{"source", "target", "kind" ("circuit_pattern"|"circuit_circuit"), "weight"}`
    """
    capped_patterns = _cap_patterns(patterns, max_patterns)

    circuits = sorted(
        {circuit for pattern in capped_patterns for circuit in pattern["circuitos"]},
        key=canonical_circuit_identity,
    )
    circuit_angles = _circuit_angles(circuits)

    circuit_nodes = [
        {
            "id": f"circuit::{circuit}",
            "kind": "circuit",
            "label": circuit,
            "soporte": None,
            "x": round(_OUTER_RADIUS * math.cos(circuit_angles[circuit]), 4),
            "y": round(_OUTER_RADIUS * math.sin(circuit_angles[circuit]), 4),
        }
        for circuit in circuits
    ]

    pattern_nodes: list[dict[str, Any]] = []
    circuit_pattern_edges: list[dict[str, Any]] = []
    angle_bucket_seen: dict[float, int] = {}
    for pattern in capped_patterns:
        tema = pattern["tema"]
        member_circuits = sorted(pattern["circuitos"], key=canonical_circuit_identity)
        angle = _pattern_angle(member_circuits, circuit_angles)
        bucket_key = round(angle, _ANGLE_BUCKET_PRECISION)
        bucket_index = angle_bucket_seen.get(bucket_key, 0)
        angle_bucket_seen[bucket_key] = bucket_index + 1
        radius = max(_INNER_RADIUS_BASE - bucket_index * _INNER_RADIUS_STEP, _INNER_RADIUS_FLOOR)

        pattern_id = f"pattern::{tema}"
        pattern_nodes.append(
            {
                "id": pattern_id,
                "kind": "pattern",
                "label": tema,
                "soporte": int(pattern["soporte"]),
                "x": round(radius * math.cos(angle), 4),
                "y": round(radius * math.sin(angle), 4),
            }
        )
        for circuit in member_circuits:
            circuit_pattern_edges.append(
                {
                    "source": f"circuit::{circuit}",
                    "target": pattern_id,
                    "kind": "circuit_pattern",
                    "weight": 1,
                }
            )

    circuit_circuit_weights: Counter[tuple[str, str]] = Counter()
    for pattern in capped_patterns:
        member_circuits = sorted(pattern["circuitos"], key=canonical_circuit_identity)
        for i in range(len(member_circuits)):
            for j in range(i + 1, len(member_circuits)):
                circuit_circuit_weights[(member_circuits[i], member_circuits[j])] += 1

    circuit_circuit_edges = [
        {
            "source": f"circuit::{a}",
            "target": f"circuit::{b}",
            "kind": "circuit_circuit",
            "weight": weight,
        }
        for (a, b), weight in sorted(circuit_circuit_weights.items())
    ]

    nodes = circuit_nodes + pattern_nodes
    edges = circuit_pattern_edges + circuit_circuit_edges
    return nodes, edges


# ---------------------------------------------------------------------------
# Radial HTML renderer (Phase 2)
# ---------------------------------------------------------------------------

_NODE_COLORS = {"circuit": "#2563eb", "pattern": "#f59e0b"}
_NODE_SIZES = {"circuit": 18, "pattern": 12}


def _vis_node(node: dict[str, Any]) -> dict[str, Any]:
    kind = node["kind"]
    if kind == "circuit":
        title = html_lib.escape(str(node["label"]))
    else:
        title = html_lib.escape(f"{node['label']} (soporte={node['soporte']})")
    return {
        "id": node["id"],
        "label": node["label"],
        "title": title,
        "group": kind,
        "color": _NODE_COLORS[kind],
        "size": _NODE_SIZES[kind],
        "x": node["x"],
        "y": node["y"],
        "fixed": {"x": True, "y": True},
    }


def _vis_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {"from": edge["source"], "to": edge["target"], "value": edge["weight"]}


def _render_html(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, output_name: str) -> str:
    """Hand-authored vis-network HTML with fixed node positions and physics
    disabled (design D1) -- byte-identical for identical `nodes`/`edges`,
    since it performs no I/O and has no non-deterministic inputs (no
    timestamps, no unordered-set iteration).
    """
    vis_nodes = [_vis_node(node) for node in nodes]
    vis_edges = [_vis_edge(edge) for edge in edges]

    nodes_json = json.dumps(vis_nodes, ensure_ascii=False)
    edges_json = json.dumps(vis_edges, ensure_ascii=False)
    network_options = {"physics": False, "interaction": {"hover": True}}
    options_json = json.dumps(network_options, ensure_ascii=False)

    title = html_lib.escape(output_name)
    stats = f"{len(vis_nodes)} nodos &middot; {len(vis_edges)} enlaces"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>grafo circular - {title}</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"
        integrity="sha384-Ux6phic9PEHJ38YtrijhkzyJ8yQlH8i/+buBR8s3mAZOJrP1gwyvAcIYl3GWtpX1"
        crossorigin="anonymous"></script>
<style>
  html, body {{ margin: 0; height: 100%; font-family: sans-serif; }}
  #graph {{ position: absolute; top: 0; left: 0; right: 260px; bottom: 0; }}
  #sidebar {{ position: absolute; top: 0; right: 0; width: 260px; bottom: 0; overflow-y: auto; padding: 12px; box-sizing: border-box; border-left: 1px solid #ddd; }}
  #search {{ width: 100%; box-sizing: border-box; margin-bottom: 8px; padding: 6px; }}
  #search-results div {{ cursor: pointer; padding: 2px 0; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; margin: 4px 0; }}
  .legend-swatch {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
  #stats {{ margin-top: 12px; color: #666; font-size: 12px; }}
</style>
</head>
<body>
<div id="graph"></div>
<div id="sidebar">
  <input id="search" type="text" placeholder="Buscar circuito o patron..." autocomplete="off">
  <div id="search-results"></div>
  <div id="info-panel">
    <h3>Info</h3>
    <div id="info-content"><span>Click en un nodo para inspeccionarlo</span></div>
  </div>
  <div id="legend-wrap">
    <h3>Leyenda</h3>
    <div class="legend-item"><span class="legend-swatch" style="background:{_NODE_COLORS["circuit"]}"></span>Circuito</div>
    <div class="legend-item"><span class="legend-swatch" style="background:{_NODE_COLORS["pattern"]}"></span>Patron</div>
  </div>
  <div id="stats">{stats}</div>
</div>
<script>
const RAW_NODES = {nodes_json};
const RAW_EDGES = {edges_json};
const NETWORK_OPTIONS = {options_json};
const nodesDS = new vis.DataSet(RAW_NODES);
const edgesDS = new vis.DataSet(RAW_EDGES);
const container = document.getElementById("graph");
const network = new vis.Network(container, {{ nodes: nodesDS, edges: edgesDS }}, NETWORK_OPTIONS);

network.on("click", function (params) {{
  const infoContent = document.getElementById("info-content");
  if (params.nodes.length === 0) {{
    infoContent.innerHTML = "<span>Click en un nodo para inspeccionarlo</span>";
    return;
  }}
  const node = nodesDS.get(params.nodes[0]);
  infoContent.innerHTML = "<strong>" + node.label + "</strong><br>" + (node.title || "");
}});

document.getElementById("search").addEventListener("input", function (event) {{
  const query = event.target.value.trim().toLowerCase();
  const results = document.getElementById("search-results");
  results.innerHTML = "";
  if (!query) {{ return; }}
  nodesDS.forEach(function (node) {{
    if (String(node.label).toLowerCase().includes(query)) {{
      const item = document.createElement("div");
      item.textContent = node.label;
      item.onclick = function () {{ network.focus(node.id, {{ scale: 1.5 }}); network.selectNodes([node.id]); }};
      results.appendChild(item);
    }}
  }});
}});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public builder + CLI (Phase 3)
# ---------------------------------------------------------------------------


def build_circuit_meta_graph(
    graph_patterns_path: str | Path | None,
    sampled: Sequence[str],
    output_path: str | Path,
    *,
    max_patterns: int | None = DEFAULT_MAX_PATTERNS,
) -> CircularGraphOutcome:
    """Build the radial meta-graph and write it to `output_path`.

    Never raises (threat matrix: path injection via `--graph-patterns`/
    `--output`, same never-raise degrade contract as
    `graph_view_builder.build_graph_view`):
    - fewer than 2 sampled circuits -> `skipped_empty` (cross-circuit
      comparison does not apply).
    - `graph_patterns_path` missing/unreadable/malformed JSON ->
      `execution_error`.
    - zero patterns meet the minimum-support threshold (via
      `informe_gerencial_contract.load_graph_patterns`) -> `skipped_empty`.
    - otherwise -> `success`, with the export written to `output_path`.
    """
    sampled_list = list(sampled)
    if len(sampled_list) < 2:
        return CircularGraphOutcome(
            status="skipped_empty",
            errors=["fewer than 2 sampled circuits -- cross-circuit comparison does not apply"],
        )

    if graph_patterns_path is None:
        return CircularGraphOutcome(status="execution_error", errors=["graph_patterns_path is required"])
    candidate = Path(graph_patterns_path)
    if not candidate.is_file():
        return CircularGraphOutcome(
            status="execution_error", errors=[f"graph patterns file not found: {candidate}"]
        )

    try:
        raw_payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return CircularGraphOutcome(status="execution_error", errors=[str(exc)])
    if not isinstance(raw_payload, dict) or not isinstance(raw_payload.get("patterns"), list):
        return CircularGraphOutcome(
            status="execution_error", errors=["graph patterns file missing 'patterns' list"]
        )

    try:
        patterns = load_graph_patterns(candidate, sampled_list) or []
    except Exception as exc:  # noqa: BLE001 -- defensive; load_graph_patterns already never raises
        return CircularGraphOutcome(status="execution_error", errors=[str(exc)])

    if not patterns:
        return CircularGraphOutcome(
            status="skipped_empty", errors=["no patterns meet the minimum support threshold"]
        )

    try:
        nodes, edges = _build_graph_elements(patterns, max_patterns=max_patterns)
        html = _render_html(nodes, edges, output_name=Path(output_path).name)
        atomic_write_text(Path(output_path), html)
    except Exception as exc:  # noqa: BLE001 -- rendering/writing must never propagate
        return CircularGraphOutcome(status="execution_error", errors=[str(exc)])

    return CircularGraphOutcome(
        status="success",
        output_path=str(output_path),
        node_count=len(nodes),
        edge_count=len(edges),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.circuit_meta_graph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_command = subparsers.add_parser("build")
    build_command.add_argument("--graph-patterns", required=True)
    build_command.add_argument("--output", required=True)
    build_command.add_argument("--sampled", nargs="+", required=True)
    build_command.add_argument("--max-patterns", type=int, default=DEFAULT_MAX_PATTERNS)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        outcome = build_circuit_meta_graph(
            args.graph_patterns,
            args.sampled,
            args.output,
            max_patterns=args.max_patterns,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status in ("success", "skipped_empty") else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
