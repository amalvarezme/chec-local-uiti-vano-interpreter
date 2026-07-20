"""Scoped cross-circuit graph-view builder for `/informe-gerencial`'s step
2.5.6 (design: "informe-gerencial-vault-graph-embed" D2/D4).

Reads the isolated `reports/vault/graphify-out/graph.json` (a vault-only
graph rebuilt fresh by step 2.5's own graphify invocation, scoped to its own
working directory and never the project-root `graphify-out/graph.json`),
filters it down to a sub-graph scoped to the batch's sampled circuits via a
seed/bridge provenance predicate, and hands the result to
`graphify.export.to_html` for rendering. The caller passes the graph path
explicitly via `--graph-json`; this module has no opinion on which graph
that is, so the isolation is enforced entirely by the caller (see
`informe-gerencial/SKILL.md` step 2.5.2).

This is the ONLY module in the `informe-gerencial-vault-graph-embed` feature
that imports/calls `graphify` directly -- `informe_gerencial_contract.py`
only ever reads the HTML file this module writes (non-goal: that contract
stays graphify-import-free). Every failure path here degrades to a
`GraphViewOutcome` -- this module never raises to its caller.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from networkx.readwrite import json_graph

from graphify.export import to_html

from chec_local_interpreter.circuit_identity import canonical_circuit_identity

SCHEMA_VERSION = "informe-gerencial-graph-view/v1"

GraphViewStatus = Literal["success", "skipped_empty", "execution_error"]


@dataclass(frozen=True)
class GraphViewOutcome:
    status: GraphViewStatus
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


def _provenance_basename(node_data: dict[str, Any]) -> str | None:
    """Recover the file basename that identifies which circuit's vault note
    this node was extracted from -- `source_file` preferred, `source_location`
    as fallback (design D2) for nodes that only carry a path in that field.
    """
    source_file = node_data.get("source_file")
    if source_file:
        return Path(str(source_file)).name
    source_location = node_data.get("source_location")
    if source_location:
        return Path(str(source_location)).name
    return None


def _circuit_communities(
    subgraph: Any,
    sampled_list: Sequence[str],
) -> tuple[dict[int, list[str]], dict[int, str]]:
    """Group `subgraph`'s retained nodes into one community PER SAMPLED
    CIRCUIT, by the same provenance predicate `build_graph_view` uses for its
    seed/bridge split -- never graphify's own topic-based `community`
    clustering attribute (design: the exported HTML's "Communities" side
    panel is a per-community checkbox filter, see `graphify.export.to_html`;
    grouping it by circuit lets a manager toggle one circuit's nodes on/off
    directly, which is the whole point of embedding this figure in a
    cross-circuit report -- grouping it by graphify's own topic clusters
    instead would neither match the panel's label to a circuit name nor let
    the manager isolate one circuit's contribution).

    Community ids are assigned in `sampled_list`'s order, so the panel is
    stable/reproducible across runs. Any retained node whose own provenance
    does not resolve to exactly one sampled circuit (a genuine bridge node
    reached only via `>= 2` seed neighbors, with no single owning vault note)
    falls into one trailing "Vinculos compartidos" community instead of being
    silently left out of every group -- `graphify.export.to_html` colors an
    ungrouped node as if it belonged to community 0, which would misattribute
    it to the first circuit in the panel.
    """
    basename_to_circuit = {f"{canonical_circuit_identity(c)}.md": c for c in sampled_list}
    circuit_index = {c: i for i, c in enumerate(sampled_list)}
    shared_cid = len(sampled_list)

    communities: dict[int, list[str]] = {}
    for node_id, node_data in subgraph.nodes(data=True):
        basename = _provenance_basename(node_data)
        circuit = basename_to_circuit.get(basename) if basename else None
        cid = circuit_index[circuit] if circuit is not None else shared_cid
        communities.setdefault(cid, []).append(node_id)

    labels = {circuit_index[c]: c for c in sampled_list}
    if shared_cid in communities:
        labels[shared_cid] = "Vinculos compartidos"
    return communities, labels


def build_graph_view(
    graph_json_path: str | Path,
    sampled: Sequence[str],
    output_path: str | Path,
    *,
    node_limit: int | None = None,
) -> GraphViewOutcome:
    """Build the seed/bridge-filtered sub-graph scoped to `sampled` circuits
    and export it via `graphify.export.to_html`.

    Never raises (threat matrix: path injection via `--graph-json`/
    `--output`, direct `graphify.export.to_html` raising): every failure mode
    degrades to `GraphViewOutcome(status="execution_error", ...)`.

    Predicate (design D2): `seed` = nodes whose provenance basename matches
    `<canonical_circuit_identity(c)>.md` for `c` in `sampled`; `bridge` =
    non-seed nodes with `>= 2` distinct seed neighbors; `keep = seed | bridge`,
    induced subgraph on `keep`. The exported panel's communities are then
    built PER CIRCUIT from `keep` via `_circuit_communities` (see there),
    with `community_labels` passed through so the panel's checkboxes are
    populated and labeled by circuit name.
    """
    sampled_list = list(sampled)
    if len(sampled_list) < 2:
        return GraphViewOutcome(
            status="skipped_empty",
            errors=["fewer than 2 sampled circuits -- cross-circuit comparison does not apply"],
        )

    try:
        candidate = Path(graph_json_path)
        data = json.loads(candidate.read_text(encoding="utf-8"))
        graph = json_graph.node_link_graph(data, edges="links")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError) as exc:
        return GraphViewOutcome(status="execution_error", errors=[str(exc)])

    try:
        canonical_targets = {f"{canonical_circuit_identity(c)}.md" for c in sampled_list}

        seed = {
            node_id
            for node_id, node_data in graph.nodes(data=True)
            if _provenance_basename(node_data) in canonical_targets
        }

        if not seed:
            return GraphViewOutcome(
                status="skipped_empty",
                errors=["no nodes matched the sampled circuits' vault notes"],
            )

        bridge = {
            node_id
            for node_id in graph.nodes()
            if node_id not in seed and len(set(graph.neighbors(node_id)) & seed) >= 2
        }

        keep = seed | bridge
        subgraph = graph.subgraph(keep).copy()

        communities, community_labels = _circuit_communities(subgraph, sampled_list)

        to_html(
            subgraph,
            communities,
            str(output_path),
            community_labels=community_labels,
            node_limit=node_limit,
        )
    except Exception as exc:  # noqa: BLE001 -- graphify export must never propagate here
        return GraphViewOutcome(status="execution_error", errors=[str(exc)])

    return GraphViewOutcome(
        status="success",
        output_path=str(output_path),
        node_count=subgraph.number_of_nodes(),
        edge_count=subgraph.number_of_edges(),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.graph_view_builder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_command = subparsers.add_parser("build")
    build_command.add_argument("--graph-json", required=True)
    build_command.add_argument("--output", required=True)
    build_command.add_argument("--sampled", nargs="+", required=True)
    build_command.add_argument("--node-limit", type=int)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        outcome = build_graph_view(
            args.graph_json,
            args.sampled,
            args.output,
            node_limit=args.node_limit,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status in ("success", "skipped_empty") else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
