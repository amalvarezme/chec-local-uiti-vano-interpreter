"""Radial causes/intervention-strategies meta-graph for the managerial report.

Replaces `circuit_meta_graph.py`'s pattern radial. The difference is the SOURCE,
not the layout: the old figure drew `graph-patterns.<grupo>.<win>.json`, i.e.
themes an LLM mined out of the vault notes after a full `graphify` rebuild --
one more hop away from the evidence, and only as available as that rebuild
(twice corrupted in production, see the SKILL's "Second resolved limitation").
This one reads the concepts the agents ALREADY wrote, straight out of each
sampled circuit's own run artifacts:

- `historical.out.json` -> `cause_hypothesis_note`, bucketed into shared causal
  themes by `informe_gerencial_contract.cause_themes` (the same helper the
  report's own "Hipótesis de causa recurrentes" prose uses, so figure and text
  can never disagree);
- `expert-alignment.out.json` -> `variables_a_priorizar`, whose
  `tipo_de_validacion_sugerida` IS the intervention the alignment agent
  proposed, plus the `coincidencias`/`diferencias` themes as cause evidence.

No `graphify`, no LLM, no dataset read: it only aggregates JSON already on disk,
so the figure renders on every run instead of degrading with the graph step.

**Why the concept nodes are anchored on canonical fields.** Measured over the
37 completed runs on disk, the agents' free prose does not merge across
circuits at all: 205 of 206 `coincidencias`/`diferencias` themes are distinct
strings, and 35 of the 36 `tipo_de_validacion_sugerida` texts written for
`CNT_TRF` are distinct. Grouping on those strings would draw one node per
circuit and show no cross-circuit relation whatsoever. What DOES recur is the
canonical part the agents share -- the variable code (`CNT_TRF` in 36 circuits,
`CNT_VN` in 33), the priority, and the causal theme. So a node is
`<intervention family> · <VARIABLE>` or a causal theme, and every free-text
sentence the agents wrote is preserved VERBATIM as that node's evidence, shown
in the info panel, never merged, never paraphrased.

Three concentric rings, read from the outside in: which circuits share which
causes, and which interventions those causes lead to.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from chec_local_interpreter.agent_output import ReportPipelineError, load_validated_agent_output
from chec_local_interpreter.agent_tools._atomic_io import atomic_write_text
from chec_local_interpreter.circuit_identity import canonical_circuit_identity
from chec_local_interpreter.glosario_variables import nombre_con_codigo
from chec_local_interpreter.informe_gerencial_contract import (
    CAUSE_THEME_KEYWORDS,
    DEFAULT_RUNS_ROOT,
    _hypothesis_clauses,
    _strip_accents,
    cause_themes,
    find_latest_run,
)

__all__ = [
    "etiqueta_de_estrategia",
    "SCHEMA_VERSION",
    "InterventionGraphOutcome",
    "build_concept_model",
    "build_graph_elements",
    "build_intervention_graph",
    "cause_themes",
    "classify_intervention",
    "main",
]

SCHEMA_VERSION = "informe-gerencial-grafo-intervencion/v1"

InterventionGraphStatus = Literal["success", "skipped_empty", "execution_error"]

# A concept has to recur across at least this many sampled circuits to earn a
# node -- same threshold, and same reason, as the report's own
# `GRAPH_PATTERNS_MIN_SUPPORT`: a concept present in one circuit is that
# circuit's finding, not the group's.
DEFAULT_MIN_SUPPORT = 2
DEFAULT_MAX_ESTRATEGIAS = 18
# How many causes a single strategy is allowed to hang from. Every cause it
# shares circuits with is still listed in its info panel; only the DRAWN edges
# are capped, because at 6 causes x 18 strategies the inner ring turns into a
# solid block and stops communicating anything.
MAX_CAUSAS_POR_ESTRATEGIA = 2

# Intervention families, keyed by the verb the alignment agent actually used.
# Order matters: first match wins. Keywords are accent- and suffix-insensitive
# stems ("revis" covers revisar/revisión/revisado), matched against the
# accent-stripped text.
INTERVENTION_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Inspección en campo", ("revis", "inspec", "audit", "program", "prioriz")),
    (
        "Contraste con fuente externa",
        ("contrast", "cruc", "cruz", "confirm", "valid", "verific", "evalu"),
    ),
    # "complet"/"complement" would also swallow "completamente", a common
    # adverb in this prose -- match the verbs themselves instead.
    ("Captura de dato faltante", ("incorpor", "solicit", "completar", "complementar")),
)
FALLBACK_FAMILY = "Otra verificación"

_PRIORITY_ORDER = {"alta": 3, "media": 2, "baja": 1}

# Ring radii are DERIVED, not fixed. A fixed inner radius is what made the
# first version unreadable: ten strategies whose wrapped labels are ~150 px
# wide need ~1500 px of circumference, and a 110 px ring only offers 691 --
# so they drew on top of each other. Each ring is now sized by how much
# circumference its own labels actually need, and the next ring out starts
# beyond it. Same failure mode, same fix, as the circular meta-graph in the
# per-circuit report: the label sets the size, not the other way round.
_CHAR_WIDTH_PX = 7.5
_NODE_PADDING_PX = 34.0
_MIN_NODE_WIDTH_PX = 70.0
_RING_GAP_PX = 190.0
_MIN_INNER_RADIUS = 130.0
_ANGLE_BUCKET_PRECISION = 6


@dataclass(frozen=True)
class InterventionGraphOutcome:
    """Mirrors `graph_view_builder.GraphViewOutcome`'s shape/conventions."""

    status: InterventionGraphStatus
    output_path: str | None = None
    node_count: int = 0
    edge_count: int = 0
    causa_count: int = 0
    estrategia_count: int = 0
    circuitos_sin_corrida: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "output_path": self.output_path,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "causa_count": self.causa_count,
            "estrategia_count": self.estrategia_count,
            "circuitos_sin_corrida": list(self.circuitos_sin_corrida),
            "errors": list(self.errors),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Concept extraction from the agents' own artifacts
# ---------------------------------------------------------------------------


def classify_intervention(text: str | None) -> str:
    """Map the alignment agent's `tipo_de_validacion_sugerida` to one of the
    `INTERVENTION_FAMILIES`, by the verb it opens with.

    This is the ONLY canonicalization applied to that text -- the sentence
    itself is kept verbatim as evidence. Never raises.
    """
    if not text:
        return FALLBACK_FAMILY
    normalized = _strip_accents(str(text))
    for familia, stems in INTERVENTION_FAMILIES:
        if any(stem in normalized for stem in stems):
            return familia
    return FALLBACK_FAMILY


def _agent_data(run_dir: Path, agent: str) -> dict[str, Any] | None:
    try:
        return load_validated_agent_output(run_dir, agent)
    except (ReportPipelineError, json.JSONDecodeError, UnicodeDecodeError, OSError, ValueError):
        return None


def collect_circuit_concepts(circuito: str, run_dir: Path) -> dict[str, Any]:
    """Read ONE circuit's causal themes and proposed interventions out of its
    own run artifacts. Never raises -- a missing or malformed artifact simply
    contributes nothing.
    """
    historical = _agent_data(run_dir, "historical") or {}
    expert = _agent_data(run_dir, "expert-alignment") or {}

    nota = historical.get("cause_hypothesis_note")
    causas = cause_themes(nota)

    temas = [
        str(item.get("tema")).strip()
        for key in ("coincidencias", "diferencias")
        for item in (expert.get(key) or [])
        if isinstance(item, dict) and item.get("tema")
    ]

    estrategias: list[dict[str, Any]] = []
    for item in expert.get("variables_a_priorizar") or []:
        if not isinstance(item, dict):
            continue
        variable = item.get("variable")
        if not variable:
            continue
        validacion = item.get("tipo_de_validacion_sugerida")
        estrategias.append(
            {
                "familia": classify_intervention(validacion),
                "variable": str(variable),
                "prioridad": item.get("prioridad"),
                "texto": str(validacion).strip() if validacion else "",
                "justificacion": str(item.get("justificacion") or "").strip(),
            }
        )

    return {
        "circuito": circuito,
        "causas": causas,
        "temas": temas,
        "nota": nota,
        "estrategias": estrategias,
    }


def _note_evidence(nota: str | None, causa: str, *, limit: int = 1) -> list[str]:
    """Pull the clause(s) of `nota` that actually triggered the `causa` bucket.

    Reuses the report annex's own clause splitter so a hypothesis renders the
    same way here as it does there. Never raises.
    """
    if not nota:
        return []
    keywords = CAUSE_THEME_KEYWORDS.get(causa, ())
    hits = [
        clause
        for clause in _hypothesis_clauses(nota)
        if any(keyword in _strip_accents(clause) for keyword in keywords)
    ]
    return hits[:limit]


def _best_priority(current: str | None, candidate: Any) -> str | None:
    """Keep the highest priority any agent gave a variable -- a strategy shared
    by two circuits is as urgent as the most urgent of them, never the average.
    """
    candidate_str = str(candidate) if candidate else None
    if candidate_str is None:
        return current
    if current is None:
        return candidate_str
    return max(current, candidate_str, key=lambda value: _PRIORITY_ORDER.get(value, 0))


def build_concept_model(
    sampled: Sequence[str],
    *,
    runs_root: str | Path | None = None,
    min_support: int = DEFAULT_MIN_SUPPORT,
) -> dict[str, Any]:
    """Aggregate every sampled circuit's concepts into the cross-circuit model
    the radial figure draws.

    Returns `{"causas": [...], "estrategias": [...], "circuitos": [...],
    "circuitos_sin_corrida": [...]}` where each concept carries its member
    `circuitos`, its `soporte`, and its verbatim per-circuit `evidencia`.
    Only concepts reaching `min_support` distinct circuits survive. Never
    raises.
    """
    root = Path(runs_root) if runs_root is not None else DEFAULT_RUNS_ROOT

    causa_circuitos: dict[str, set[str]] = defaultdict(set)
    causa_evidencia: dict[str, list[dict[str, str]]] = defaultdict(list)
    estrategia_circuitos: dict[str, set[str]] = defaultdict(set)
    estrategia_evidencia: dict[str, list[dict[str, str]]] = defaultdict(list)
    estrategia_meta: dict[str, dict[str, Any]] = {}
    # Per-circuit membership, needed to weight the causa->estrategia edges by
    # how many circuits actually show BOTH.
    causas_por_circuito: dict[str, set[str]] = {}
    estrategias_por_circuito: dict[str, set[str]] = {}

    con_corrida: list[str] = []
    sin_corrida: list[str] = []

    for circuito in sampled:
        run_dir = find_latest_run(circuito, runs_root=root)
        if run_dir is None:
            sin_corrida.append(circuito)
            continue
        con_corrida.append(circuito)
        concepts = collect_circuit_concepts(circuito, run_dir)

        propias_causas = set(concepts["causas"])
        causas_por_circuito[circuito] = propias_causas
        for causa in concepts["causas"]:
            causa_circuitos[causa].add(circuito)
            # Only the alignment agent's themes that bucket into THIS same
            # cause become its evidence. Attaching every theme the circuit
            # wrote to every cause it has would multiply the same sentences
            # across unrelated nodes and stop being evidence for anything.
            aportes = [tema for tema in concepts["temas"] if causa in cause_themes(tema)]
            # The alignment agent does not always phrase a theme the way the
            # bucket is named (nothing it wrote mentions "media tension", for
            # instance). Falling back to the historical agent's own sentence --
            # the one that produced the bucket in the first place -- keeps
            # every cause node backed by a quotable line instead of an empty
            # panel.
            if not aportes:
                aportes = _note_evidence(concepts["nota"], causa)
            for texto in aportes:
                causa_evidencia[causa].append({"circuito": circuito, "texto": texto})

        propias_estrategias: set[str] = set()
        for entry in concepts["estrategias"]:
            concepto = f"{entry['familia']} · {entry['variable']}"
            propias_estrategias.add(concepto)
            estrategia_circuitos[concepto].add(circuito)
            meta = estrategia_meta.setdefault(
                concepto,
                {"familia": entry["familia"], "variable": entry["variable"], "prioridad": None},
            )
            meta["prioridad"] = _best_priority(meta["prioridad"], entry["prioridad"])
            if entry["texto"]:
                estrategia_evidencia[concepto].append(
                    {
                        "circuito": circuito,
                        "texto": entry["texto"],
                        "justificacion": entry["justificacion"],
                    }
                )
        estrategias_por_circuito[circuito] = propias_estrategias

    causas = [
        {
            "concepto": concepto,
            "circuitos": sorted(circuitos, key=canonical_circuit_identity),
            "soporte": len(circuitos),
            "evidencia": causa_evidencia[concepto],
        }
        for concepto, circuitos in causa_circuitos.items()
        if len(circuitos) >= min_support
    ]
    causas.sort(key=lambda item: (-item["soporte"], item["concepto"]))

    estrategias = [
        {
            "concepto": concepto,
            "familia": estrategia_meta[concepto]["familia"],
            "variable": estrategia_meta[concepto]["variable"],
            "prioridad": estrategia_meta[concepto]["prioridad"],
            "circuitos": sorted(circuitos, key=canonical_circuit_identity),
            "soporte": len(circuitos),
            "evidencia": estrategia_evidencia[concepto],
        }
        for concepto, circuitos in estrategia_circuitos.items()
        if len(circuitos) >= min_support
    ]
    estrategias.sort(
        key=lambda item: (
            -item["soporte"],
            -_PRIORITY_ORDER.get(item["prioridad"] or "", 0),
            item["concepto"],
        )
    )

    return {
        "causas": causas,
        "estrategias": estrategias,
        "circuitos": sorted(con_corrida, key=canonical_circuit_identity),
        "circuitos_sin_corrida": sin_corrida,
        "causas_por_circuito": causas_por_circuito,
        "estrategias_por_circuito": estrategias_por_circuito,
    }


# ---------------------------------------------------------------------------
# Radial layout
# ---------------------------------------------------------------------------


#: Margen angular que se deja en las puntas de cada semicircunferencia. Sin el, el primer
#: y el ultimo nodo caen exactamente sobre la vertical (coseno 0) y quedan pisando la
#: frontera entre las dos mitades, que es justo lo que la disposicion quiere separar.
_MARGEN_ARCO = 0.16


def etiqueta_de_estrategia(concepto: str) -> str:
    """`Inspección en campo · NR_T` -> `Inspección en campo · Riesgo por vegetación... (NR_T)`.

    El concepto sigue siendo la IDENTIDAD -- es la clave con la que se agrupan las
    estrategias entre circuitos y la que viaja al `.resumen.json` --, asi que no se toca:
    solo se traduce lo que se DIBUJA. Un informe que solo diera el nombre bonito obligaria
    a traducir de vuelta a mano para buscar la columna en el dataset; uno que solo diera el
    codigo obliga a saberse los nombres de columna de este CSV en particular.
    """
    if " · " not in concepto:
        return concepto
    familia, _, variable = concepto.partition(" · ")
    return f"{familia} · {nombre_con_codigo(variable)}"


def _arc_angles(count: int, desde: float, hasta: float) -> list[float]:
    """`count` angulos repartidos por igual dentro de `[desde, hasta]`.

    Con un solo elemento va al centro del arco y no a una punta: un nodo suelto pegado al
    borde se lee como si le faltaran vecinos.
    """
    if count <= 0:
        return []
    if count == 1:
        return [(desde + hasta) / 2.0]
    paso = (hasta - desde) / (count - 1)
    return [desde + paso * i for i in range(count)]


def _circuit_angles(circuits: Sequence[str]) -> dict[str, float]:
    """Los circuitos ocupan la semicircunferencia IZQUIERDA.

    Antes los tres anillos eran circunferencias completas y concentricas, y toda arista
    circuito -> causa podia salir en cualquier direccion: con 7 circuitos y 4 causas la
    figura era una maraña. Con las dos mitades enfrentadas -- circuitos a la izquierda,
    causas y estrategias a la derecha -- TODA arista cruza el centro una sola vez y en el
    mismo sentido, que es lo que deja seguirla con la vista.
    """
    ordered = sorted(circuits, key=canonical_circuit_identity)
    angulos = _arc_angles(
        len(ordered),
        math.pi / 2 + _MARGEN_ARCO,
        3 * math.pi / 2 - _MARGEN_ARCO,
    )
    return {circuit: angulo for circuit, angulo in zip(ordered, angulos)}


def _mean_angle(members: Sequence[str], circuit_angles: dict[str, float]) -> float:
    """Circular mean of the member circuits' angles -- the arithmetic mean is
    wrong on a circle (averaging 350 and 10 degrees must give 0, not 180).
    """
    known = [circuit_angles[c] for c in members if c in circuit_angles]
    if not known:
        return 0.0
    xs = sum(math.cos(angle) for angle in known)
    ys = sum(math.sin(angle) for angle in known)
    return math.atan2(ys / len(known), xs / len(known))


def _place(
    concepts: Sequence[dict[str, Any]],
    circuit_angles: dict[str, float],
    *,
    base_radius: float,
) -> list[tuple[dict[str, Any], float, float]]:
    """Spread the ring's concepts evenly, ORDERED by the circular mean of their
    member circuits.

    Placing each concept exactly at that mean is the obvious thing to do, and
    it is what the first version did -- but the means bunch up hard (the
    dominant causes share most of the same circuits), so ten strategies drew
    almost on top of one another and the ring was unreadable. Keeping the
    ORDER but distributing the angles evenly preserves "this concept sits
    towards its circuits" while guaranteeing no two nodes on a ring collide.
    Ties in the mean angle break on `concepto`, so the layout stays
    deterministic.
    """
    ordered = sorted(
        concepts,
        key=lambda concept: (
            round(_mean_angle(concept["circuitos"], circuit_angles), _ANGLE_BUCKET_PRECISION),
            concept["concepto"],
        ),
    )
    # La mitad DERECHA, de arriba abajo. El orden es el de la media circular de sus
    # circuitos, asi que un concepto queda enfrentado a los circuitos que lo nombran y su
    # arista cruza el centro casi horizontal, no en diagonal.
    #
    # El recorrido va de `pi/2` a `-pi/2` (y no al reves) para que el concepto cuya media
    # cae ARRIBA en la mitad izquierda quede tambien ARRIBA en la derecha. Invertirlo
    # cruzaba todas las aristas en aspa.
    angulos = _arc_angles(
        len(ordered),
        math.pi / 2 - _MARGEN_ARCO,
        -math.pi / 2 + _MARGEN_ARCO,
    )
    return [
        (
            concept,
            round(base_radius * math.cos(angle), 4),
            round(base_radius * math.sin(angle), 4),
        )
        for concept, angle in zip(ordered, angulos)
    ]


def _ring_radius(labels: Sequence[str], *, at_least: float) -> float:
    """Smallest radius that keeps every node on this ring clear of its
    neighbours, floored at `at_least`.

    Sized on the WIDEST label, not the average. Nodes are spaced at equal
    angles, so two wide neighbours only get the average share of the
    circumference -- and that is exactly what still overlapped when this was
    computed from the sum of widths. The gap between adjacent nodes is the
    chord `2r*sin(pi/n)`, not the arc, so the radius is solved from the chord
    directly.
    """
    if len(labels) < 2:
        return at_least
    widest = max(
        max(
            _MIN_NODE_WIDTH_PX,
            max(len(line) for line in _wrap_label(label).split("\n")) * _CHAR_WIDTH_PX,
        )
        for label in labels
    ) + _NODE_PADDING_PX
    needed = widest / (2 * math.sin(math.pi / len(labels)))
    return max(at_least, needed)


def _wrap_label(text: str) -> str:
    """Break a label at its own separator so vis-network draws it on two short
    lines instead of one wide ellipse. Width is what makes these rings
    collide, not height.
    """
    for separator in (" · ", " / "):
        if separator in text:
            head, _, tail = text.partition(separator)
            return f"{head.strip()}\n{tail.strip()}"
    return text


def _scaled_size(kind: str, soporte: int | None, total_circuits: int) -> int:
    """Grow a concept node with the share of circuits it covers, so the
    dominant cause reads as dominant at a glance.
    """
    base = _NODE_SIZES[kind]
    if not soporte or total_circuits <= 0:
        return base
    return int(round(base * (0.75 + 0.75 * min(soporte / total_circuits, 1.0))))


def build_graph_elements(
    model: dict[str, Any],
    *,
    max_estrategias: int | None = DEFAULT_MAX_ESTRATEGIAS,
    max_causas_por_estrategia: int = MAX_CAUSAS_POR_ESTRATEGIA,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Turn the concept model into the radial graph's nodes and edges.

    Pure function -- same model in, byte-identical lists out. Three rings
    (`circuito` outermost, `causa`, `estrategia` innermost) and two edge kinds:
    `circuito_causa` (this circuit's hypothesis names that cause) and
    `causa_estrategia` (both appear in the same circuits). There is deliberately
    NO circuit-to-strategy edge: the figure's whole point is that an
    intervention is reached THROUGH a cause. Any strategy left with no cause
    edge is dropped rather than drawn floating.
    """
    causas = list(model["causas"])
    estrategias = list(model["estrategias"])
    if max_estrategias is not None and max_estrategias > 0:
        estrategias = estrategias[:max_estrategias]

    circuitos = sorted(
        {c for concept in causas + estrategias for c in concept["circuitos"]},
        key=canonical_circuit_identity,
    )
    if not circuitos:
        return [], []
    circuit_angles = _circuit_angles(circuitos)

    # Radios de dentro hacia fuera, siguiendo la cadena que la figura cuenta:
    # circuito -> causa -> estrategia. La CAUSA va pegada al centro y la ESTRATEGIA por
    # fuera, asi la mitad derecha se lee de dentro hacia afuera igual que se lee la frase.
    #
    # Antes la estrategia era el anillo mas interno y la causa el del medio, porque los
    # tres eran circunferencias completas y lo que mandaba era el conteo de nodos. Con las
    # dos mitades enfrentadas manda la direccion de lectura.
    #
    # Cada arco solo tiene que despejar sus PROPIAS etiquetas, y como ahora ocupa media
    # vuelta y no una entera, sus nodos van al doble de apretados: el radio se calcula
    # sobre el doble de nodos para conservar el mismo aire entre vecinos.
    radio_causa = _ring_radius(
        [item["concepto"] for item in causas] * 2, at_least=_MIN_INNER_RADIUS
    )
    radio_estrategia = _ring_radius(
        # La etiqueta DIBUJADA, no el concepto: al expandir el codigo a su nombre el texto
        # crece, y un radio calculado sobre el codigo pelado deja los nodos pisandose.
        [etiqueta_de_estrategia(item["concepto"]) for item in estrategias] * 2,
        at_least=radio_causa + _RING_GAP_PX,
    )
    # Los circuitos van en la otra mitad, a la distancia de la estrategia: las dos mitades
    # se ven del mismo tamano y el centro queda libre para que crucen las aristas.
    radio_circuito = _ring_radius(circuitos * 2, at_least=radio_estrategia)

    causa_ids = {concept["concepto"]: f"causa::{concept['concepto']}" for concept in causas}
    estrategia_ids = {
        concept["concepto"]: f"estrategia::{concept['concepto']}" for concept in estrategias
    }

    # causa -> estrategia, weighted by how many circuits show both. Capped per
    # strategy so the inner ring stays readable (see MAX_CAUSAS_POR_ESTRATEGIA).
    causas_por_circuito = model.get("causas_por_circuito", {})
    estrategias_por_circuito = model.get("estrategias_por_circuito", {})
    edges: list[dict[str, Any]] = []
    conectadas: set[str] = set()
    for estrategia in estrategias:
        pesos: list[tuple[int, str]] = []
        for causa in causas:
            compartidos = sum(
                1
                for circuito in estrategia["circuitos"]
                if causa["concepto"] in causas_por_circuito.get(circuito, set())
                and estrategia["concepto"] in estrategias_por_circuito.get(circuito, set())
            )
            if compartidos:
                pesos.append((compartidos, causa["concepto"]))
        pesos.sort(key=lambda item: (-item[0], item[1]))
        for peso, causa_concepto in pesos[:max_causas_por_estrategia]:
            conectadas.add(estrategia["concepto"])
            edges.append(
                {
                    "source": causa_ids[causa_concepto],
                    "target": estrategia_ids[estrategia["concepto"]],
                    "kind": "causa_estrategia",
                    "weight": peso,
                }
            )

    estrategias = [item for item in estrategias if item["concepto"] in conectadas]
    estrategia_ids = {
        concept["concepto"]: estrategia_ids[concept["concepto"]] for concept in estrategias
    }

    nodes: list[dict[str, Any]] = [
        {
            "id": f"circuito::{circuito}",
            "kind": "circuito",
            "label": circuito,
            "soporte": None,
            "detalle": [],
            "x": round(radio_circuito * math.cos(circuit_angles[circuito]), 4),
            "y": round(radio_circuito * math.sin(circuit_angles[circuito]), 4),
        }
        for circuito in circuitos
    ]

    for concept, x, y in _place(causas, circuit_angles, base_radius=radio_causa):
        nodes.append(
            {
                "id": causa_ids[concept["concepto"]],
                "kind": "causa",
                "label": concept["concepto"],
                "soporte": concept["soporte"],
                "total_circuitos": len(circuitos),
                "detalle": _evidence_lines(concept["evidencia"]),
                "circuitos": concept["circuitos"],
                "x": x,
                "y": y,
            }
        )
        for circuito in concept["circuitos"]:
            edges.append(
                {
                    "source": f"circuito::{circuito}",
                    "target": causa_ids[concept["concepto"]],
                    "kind": "circuito_causa",
                    "weight": 1,
                }
            )

    for concept, x, y in _place(estrategias, circuit_angles, base_radius=radio_estrategia):
        nodes.append(
            {
                "id": estrategia_ids[concept["concepto"]],
                "kind": "estrategia",
                "label": etiqueta_de_estrategia(concept["concepto"]),
                "soporte": concept["soporte"],
                "total_circuitos": len(circuitos),
                "prioridad": concept["prioridad"],
                "detalle": _evidence_lines(concept["evidencia"]),
                "circuitos": concept["circuitos"],
                "x": x,
                "y": y,
            }
        )

    edges.sort(key=lambda edge: (edge["kind"], edge["source"], edge["target"]))
    return nodes, edges


def _evidence_lines(evidencia: Sequence[dict[str, str]]) -> list[str]:
    """One verbatim line per circuit, deduplicated and ordered -- the agents'
    own sentences, never paraphrased.
    """
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for item in evidencia:
        key = (item.get("circuito", ""), item.get("texto", ""))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        lines.append(f"{key[0]}: {key[1]}")
    return sorted(lines)


# ---------------------------------------------------------------------------
# Radial HTML renderer
# ---------------------------------------------------------------------------

_NODE_COLORS = {"circuito": "#2563eb", "causa": "#dc2626", "estrategia": "#059669"}
_NODE_SIZES = {"circuito": 16, "causa": 24, "estrategia": 20}
_EDGE_COLORS = {"circuito_causa": "#cbd5e1", "causa_estrategia": "#94a3b8"}


def _vis_node(node: dict[str, Any]) -> dict[str, Any]:
    kind = node["kind"]
    if kind == "circuito":
        title = str(node["label"])
    elif kind == "causa":
        title = f"{node['label']} — presente en {node['soporte']} circuitos"
    else:
        prioridad = node.get("prioridad") or "sin prioridad"
        title = f"{node['label']} — {node['soporte']} circuitos, prioridad {prioridad}"
    return {
        "id": node["id"],
        "label": _wrap_label(str(node["label"])),
        "title": title,
        "group": kind,
        "color": _NODE_COLORS[kind],
        "size": _scaled_size(kind, node.get("soporte"), node.get("total_circuitos", 0)),
        "x": node["x"],
        "y": node["y"],
        "fixed": {"x": True, "y": True},
        "detalle": node.get("detalle", []),
        "circuitos": node.get("circuitos", []),
    }


def _vis_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": edge["source"],
        "to": edge["target"],
        "value": edge["weight"],
        "color": {"color": _EDGE_COLORS[edge["kind"]], "opacity": 0.55},
    }


def _script_safe_json(payload: Any) -> str:
    """Serialize `payload` for embedding inside an inline `<script>` block.

    The evidence carried here is agent-authored free text. A literal
    `</script>` anywhere in it would close the block early and drop the rest of
    the page on the floor -- so `<`, `>` and `&` are emitted as `\\u003c`-style
    escapes, which JSON and JavaScript both read back as the original
    characters. Deterministic (`sort_keys=True`).
    """
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_ETIQUETA_ANILLO = {"circuito": "Circuitos", "causa": "Causas",
                    "estrategia": "Estrategias"}
#: Cuantos nodos de un anillo llevan rotulo escrito. El resto se dibuja igual -- el
#: anillo es una ESTRUCTURA y quitar nodos mentiria sobre ella -- pero su nombre se lee
#: en el hover. Con mas de esto alrededor de un circulo no se lee ninguno.
MAX_ROTULOS_ANILLO = 45


#: Ancho maximo, en caracteres, de una linea del globo de hover.
#: Plotly NO envuelve el texto del hover: dibuja el globo tan ancho como su linea mas
#: larga. Una frase de agente de 200 caracteres lo hacia mas ancho que la figura y el
#: navegador lo recortaba por los DOS lados a la vez -- se veia el centro de cada linea y
#: se perdian el principio y el final. 90 cabe holgado en el ancho del informe.
ANCHO_HOVER = 90


def _partir_en_lineas(texto: str, ancho: int = ANCHO_HOVER) -> list[str]:
    """`texto` repartido en lineas de a lo sumo `ancho` caracteres, sin partir palabras.

    Una palabra mas larga que `ancho` se deja entera y desborda: cortarla la vuelve
    ilegible, y en este dominio esas palabras son codigos (`PROMEDIO_KWH_TRF`) que hay
    que poder copiar.
    """
    lineas: list[str] = []
    actual = ""
    for palabra in texto.split():
        if actual and len(actual) + 1 + len(palabra) > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}" if actual else palabra
    if actual:
        lineas.append(actual)
    return lineas or [""]


def _hover_de_nodo(node: dict[str, Any]) -> str:
    """Lo que el panel lateral del iframe mostraba al hacer clic.

    Sin iframe el sitio natural es el hover, y ahi va lo mismo: el concepto, en cuantos
    circuitos aparece, y las frases que los agentes escribieron -- VERBATIM, que es todo
    el punto de este grafo: no se parafrasean ni se mezclan.
    """
    lineas = [f"<b>{html_lib.escape(str(node['label']))}</b>"]
    soporte = node.get("soporte")
    total = node.get("total_circuitos")
    if soporte is not None:
        lineas.append(f"Presente en {soporte} de {total} circuitos"
                      if total else f"Presente en {soporte} circuitos")
    prioridad = node.get("prioridad")
    if prioridad:
        lineas.append(f"Prioridad: {html_lib.escape(str(prioridad))}")
    detalle = list(node.get("detalle") or [])
    for linea in detalle[:6]:
        lineas.extend(_partir_en_lineas(html_lib.escape(str(linea))))
    if len(detalle) > 6:
        lineas.append(f"… y {len(detalle) - 6} más")
    return "<br>".join(lineas)


def figura_plotly(nodes: Sequence[dict[str, Any]], edges: Sequence[dict[str, Any]]):
    """El grafo radial de conceptos, en Plotly.

    Se dibujaba con `vis-network` desde un CDN y viajaba al informe dentro de un iframe.
    Eso costaba tres cosas: una segunda biblioteca de grafo para un anillo que se lee
    igual que el del informe por circuito y el del tablero; un iframe que no hereda la
    hoja de estilos de la pagina ni su `plotly.js` y no crece con su ancho; y una
    dependencia mas por CDN con su `integrity` clavado a una version.

    El MODELO no cambia. `build_graph_elements` sigue siendo la misma funcion pura, con
    sus tres anillos y sus posiciones fijas, y aqui NO se recalcula ninguna: hacerlo
    abriria la puerta a que el dibujo y el resumen JSON del mismo grafo se separen.

    Una traza de marcadores por anillo, para que la leyenda pueda apagarlos por
    separado -- que es justo lo que el iframe no dejaba hacer desde el informe.
    """
    if not nodes:
        return None

    import plotly.graph_objects as go

    from chec_local_interpreter.simulador_variables import rotacion_radial

    posicion = {n["id"]: (float(n["x"]), float(n["y"])) for n in nodes}
    fig = go.Figure()

    # Las aristas primero, para que queden DEBAJO de los nodos. Una traza por arista y
    # no una sola con `None` entre segmentos: el grosor va ligado al peso -- en cuantos
    # circuitos coinciden causa y estrategia -- y en una traza unica el ancho de linea
    # es una propiedad de la traza entera.
    pesos = [int(e.get("weight") or 1) for e in edges] or [1]
    maximo = max(pesos) or 1
    for arista in edges:
        origen = posicion.get(arista["source"])
        destino = posicion.get(arista["target"])
        if origen is None or destino is None:
            continue
        proporcion = int(arista.get("weight") or 1) / maximo
        fig.add_trace(go.Scatter(
            x=[origen[0], destino[0]], y=[origen[1], destino[1]], mode="lines",
            line=dict(color=_EDGE_COLORS.get(arista["kind"], "#cbd5e1"),
                      width=0.8 + 3.2 * proporcion),
            opacity=0.35 + 0.5 * proporcion,
            hoverinfo="skip", showlegend=False,
        ))

    for kind in ("circuito", "causa", "estrategia"):
        del_anillo = [n for n in nodes if n["kind"] == kind]
        if not del_anillo:
            continue
        fig.add_trace(go.Scatter(
            x=[float(n["x"]) for n in del_anillo],
            y=[float(n["y"]) for n in del_anillo],
            mode="markers", name=_ETIQUETA_ANILLO[kind],
            marker=dict(
                size=[_scaled_size(kind, n.get("soporte"),
                                   n.get("total_circuitos", 0)) * 0.75
                      for n in del_anillo],
                color=_NODE_COLORS[kind],
                line=dict(width=1.0, color="#ffffff")),
            hovertext=[_hover_de_nodo(n) for n in del_anillo], hoverinfo="text",
        ))

    # Los rotulos van como ANOTACIONES: un `Scatter` no sabe girar su texto, y
    # horizontales se enciman entre vecinos del mismo anillo.
    for node in list(nodes)[:MAX_ROTULOS_ANILLO]:
        x, y = float(node["x"]), float(node["y"])
        angulo, anclaje = rotacion_radial(x, y)
        radio = math.hypot(x, y) or 1.0
        fig.add_annotation(
            x=x * (1.0 + 26.0 / radio), y=y * (1.0 + 26.0 / radio),
            # Envuelto por su propio separador, NO cortado. `_ring_radius` ya midio
            # este anillo con el rotulo partido en dos lineas, asi que el hueco esta
            # reservado; el `[:38]` de antes dejaba "Riesgo por veget" en un espacio
            # que ya cabia entero.
            text=html_lib.escape(_wrap_label(str(node["label"]))).replace("\n", "<br>"),
            showarrow=False, textangle=angulo, xanchor=anclaje, yanchor="middle",
            font=dict(size=10, color="#334155"),
        )

    limite = max((math.hypot(float(n["x"]), float(n["y"])) for n in nodes), default=1.0)
    limite *= 1.35
    fig.update_layout(
        height=620, margin=dict(l=10, r=10, t=28, b=10),
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        hoverlabel=dict(align="left", font_size=11),
    )
    fig.update_xaxes(visible=False, range=[-limite, limite])
    # `scaleanchor` para que los tres anillos sean CIRCULOS: sin el, el ancho del
    # contenedor decide la forma y dejan de leerse como anillos.
    fig.update_yaxes(visible=False, range=[-limite, limite],
                     scaleanchor="x", scaleratio=1)
    return fig


def render_html_plotly(
    nodes: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    *,
    output_name: str,
) -> str:
    """La pagina del grafo, con Plotly y sin `vis-network`.

    Se sigue escribiendo un HTML completo a disco -- el informe gerencial lo embebe y
    tambien se abre suelto --, pero ahora carga `plotly.js`, el mismo motor que el
    informe por circuito.
    """
    figura = figura_plotly(nodes, edges)
    # `div_id` FIJO. Sin el, `to_html` genera un UUID nuevo en cada llamada y el archivo
    # deja de ser byte-identico para las mismas entradas -- que es un contrato de este
    # modulo, no un detalle: es lo que permite ver si el grafo cambio de verdad
    # comparando dos corridas. Se deriva del nombre del destino y no del contenido,
    # porque el mismo grafo escrito en dos sitios distintos ya se distingue por su
    # titulo.
    cuerpo = ("<p>El modelo de conceptos quedó vacío.</p>" if figura is None
              else figura.to_html(full_html=False, include_plotlyjs="cdn",
                                  div_id="grafo-conceptos"))
    titulo = html_lib.escape(output_name)
    return (
        "<!DOCTYPE html>\n<html lang=\"es\">\n<head>\n<meta charset=\"UTF-8\">\n"
        f"<title>grafo radial de causas y estrategias - {titulo}</title>\n"
        "<style>html,body{margin:0;font-family:'Segoe UI',Arial,sans-serif;"
        "background:#ffffff;color:#2b2b2b;}</style>\n</head>\n<body>\n"
        f"{cuerpo}\n</body>\n</html>\n"
    )


def _render_html(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, output_name: str
) -> str:
    """Hand-authored vis-network HTML with fixed node positions and physics
    disabled.

    Hand-authored for the same reason `circuit_meta_graph` was:
    `graphify.export.to_html` emits nodes with no `x`/`y` and hardcodes
    `physics: {enabled: true}`, so a fixed radial layout is impossible through
    it. Byte-identical for identical inputs -- no timestamps, no unordered
    iteration.
    """
    vis_nodes = [_vis_node(node) for node in nodes]
    vis_edges = [_vis_edge(edge) for edge in edges]

    nodes_json = _script_safe_json(vis_nodes)
    edges_json = _script_safe_json(vis_edges)
    options_json = json.dumps(
        {
            "physics": False,
            "interaction": {"hover": True, "tooltipDelay": 120},
            "nodes": {"font": {"size": 15, "face": "sans-serif"}},
            "edges": {"smooth": False, "scaling": {"min": 1, "max": 5}},
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    causas = sum(1 for node in nodes if node["kind"] == "causa")
    estrategias = sum(1 for node in nodes if node["kind"] == "estrategia")
    circuitos = sum(1 for node in nodes if node["kind"] == "circuito")
    stats = (
        f"{circuitos} circuitos &middot; {causas} causas &middot; "
        f"{estrategias} estrategias &middot; {len(vis_edges)} enlaces"
    )
    title = html_lib.escape(output_name)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>grafo radial de causas y estrategias - {title}</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"
        integrity="sha384-Ux6phic9PEHJ38YtrijhkzyJ8yQlH8i/+buBR8s3mAZOJrP1gwyvAcIYl3GWtpX1"
        crossorigin="anonymous"></script>
<style>
  html, body {{ margin: 0; height: 100%; font-family: sans-serif; }}
  #graph {{ position: absolute; top: 0; left: 0; right: 300px; bottom: 0; }}
  #sidebar {{ position: absolute; top: 0; right: 0; width: 300px; bottom: 0; overflow-y: auto;
              padding: 12px; box-sizing: border-box; border-left: 1px solid #ddd; font-size: 13px; }}
  #search {{ width: 100%; box-sizing: border-box; margin-bottom: 8px; padding: 6px; }}
  #search-results div {{ cursor: pointer; padding: 2px 0; color: #2563eb; }}
  h3 {{ margin: 14px 0 6px; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: #475569; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; margin: 4px 0; }}
  .legend-swatch {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
  .evidence {{ margin: 6px 0 0; padding-left: 16px; }}
  .evidence li {{ margin-bottom: 5px; line-height: 1.35; }}
  #stats {{ margin-top: 14px; color: #64748b; font-size: 12px; }}
  .hint {{ color: #64748b; font-size: 12px; line-height: 1.4; }}
</style>
</head>
<body>
<div id="graph"></div>
<div id="sidebar">
  <input id="search" type="text" placeholder="Buscar circuito, causa o estrategia..." autocomplete="off">
  <div id="search-results"></div>
  <h3>Detalle</h3>
  <div id="info-content" class="hint">Click en un nodo para ver que escribieron los agentes.</div>
  <h3>Leyenda</h3>
  <div class="legend-item"><span class="legend-swatch" style="background:{_NODE_COLORS["circuito"]}"></span>Circuito muestreado</div>
  <div class="legend-item"><span class="legend-swatch" style="background:{_NODE_COLORS["causa"]}"></span>Causa compartida</div>
  <div class="legend-item"><span class="legend-swatch" style="background:{_NODE_COLORS["estrategia"]}"></span>Estrategia de intervencion</div>
  <p class="hint">Se lee de afuera hacia adentro: los circuitos comparten causas, y cada causa lleva
  a las intervenciones que los agentes propusieron. Solo aparecen conceptos presentes en dos o mas
  circuitos.</p>
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

function escapeHtml(value) {{
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}}

function renderInfo(node) {{
  const parts = ["<strong>" + escapeHtml(node.label) + "</strong>"];
  parts.push("<div class=\\"hint\\">" + escapeHtml(node.title) + "</div>");
  const circuitos = node.circuitos || [];
  if (circuitos.length) {{
    parts.push("<div class=\\"hint\\">Circuitos: " + escapeHtml(circuitos.join(", ")) + "</div>");
  }}
  const detalle = node.detalle || [];
  if (detalle.length) {{
    parts.push("<ul class=\\"evidence\\">" +
      detalle.map(function (line) {{ return "<li>" + escapeHtml(line) + "</li>"; }}).join("") +
      "</ul>");
  }}
  return parts.join("");
}}

network.on("click", function (params) {{
  const infoContent = document.getElementById("info-content");
  if (params.nodes.length === 0) {{
    infoContent.className = "hint";
    infoContent.innerHTML = "Click en un nodo para ver que escribieron los agentes.";
    return;
  }}
  infoContent.className = "";
  infoContent.innerHTML = renderInfo(nodesDS.get(params.nodes[0]));
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
      item.onclick = function () {{ network.focus(node.id, {{ scale: 1.4 }}); network.selectNodes([node.id]); }};
      results.appendChild(item);
    }}
  }});
}});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public builder + CLI
# ---------------------------------------------------------------------------


def summary_path(output_path: str | Path) -> Path:
    """Sibling JSON the report reads back to print the causes/strategies as
    TEXT next to the figure.

    A file handoff rather than an import: `informe_gerencial_contract` is this
    module's own dependency (for `cause_themes`, `find_latest_run`, ...), so
    importing back the other way would close a cycle. Same
    "builder writes a file, the contract reads it" convention
    `--graph-patterns` already uses.
    """
    destination = Path(output_path)
    return destination.with_suffix(destination.suffix + ".resumen.json")


def _summary_json_text(model: dict[str, Any], nodes: Sequence[dict[str, Any]]) -> str:
    """Serialize ONLY the concepts that actually made it into the drawn graph,
    so the text next to the figure can never name a cause or a strategy the
    figure does not show.
    """
    drawn = {node["label"] for node in nodes}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "causas": [
            {
                "concepto": item["concepto"],
                "soporte": item["soporte"],
                "circuitos": item["circuitos"],
            }
            for item in model["causas"]
            if item["concepto"] in drawn
        ],
        "estrategias": [
            {
                "concepto": item["concepto"],
                "soporte": item["soporte"],
                "prioridad": item["prioridad"],
                "circuitos": item["circuitos"],
            }
            for item in model["estrategias"]
            if item["concepto"] in drawn
        ],
        "circuitos_sin_corrida": list(model["circuitos_sin_corrida"]),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def build_intervention_graph(
    sampled: Sequence[str],
    output_path: str | Path,
    *,
    runs_root: str | Path | None = None,
    min_support: int = DEFAULT_MIN_SUPPORT,
    max_estrategias: int | None = DEFAULT_MAX_ESTRATEGIAS,
) -> InterventionGraphOutcome:
    """Build the radial causes/strategies graph and write it to `output_path`.

    Never raises -- same degrade contract as `graph_view_builder.build_graph_view`:
    - fewer than 2 sampled circuits -> `skipped_empty`;
    - no concept shared by `min_support` circuits -> `skipped_empty`;
    - anything unwritable/unrenderable -> `execution_error`;
    - otherwise -> `success`.
    """
    sampled_list = [str(item) for item in sampled]
    if len(sampled_list) < 2:
        return InterventionGraphOutcome(
            status="skipped_empty",
            errors=["menos de 2 circuitos muestreados -- no hay comparacion cross-circuito"],
        )

    try:
        model = build_concept_model(sampled_list, runs_root=runs_root, min_support=min_support)
    except Exception as exc:  # noqa: BLE001 -- reading run artifacts must never propagate
        return InterventionGraphOutcome(status="execution_error", errors=[str(exc)])

    sin_corrida = list(model["circuitos_sin_corrida"])
    if not model["causas"]:
        return InterventionGraphOutcome(
            status="skipped_empty",
            circuitos_sin_corrida=sin_corrida,
            errors=[f"ninguna causa compartida por {min_support} o mas circuitos muestreados"],
        )

    try:
        nodes, edges = build_graph_elements(model, max_estrategias=max_estrategias)
        if not nodes:
            return InterventionGraphOutcome(
                status="skipped_empty",
                circuitos_sin_corrida=sin_corrida,
                errors=["el modelo de conceptos quedo vacio tras el armado del grafo"],
            )
        # Plotly y no `vis-network`: el informe por circuito, el tablero y este
        # grafo dibujan anillos que se leen igual, y tenerlos en dos motores
        # obliga a reconciliar dos comportamientos de zoom, hover y arrastre.
        html = render_html_plotly(nodes, edges, output_name=Path(output_path).name)
        atomic_write_text(Path(output_path), html)
        atomic_write_text(summary_path(output_path), _summary_json_text(model, nodes))
    except Exception as exc:  # noqa: BLE001 -- rendering/writing must never propagate
        return InterventionGraphOutcome(
            status="execution_error", circuitos_sin_corrida=sin_corrida, errors=[str(exc)]
        )

    return InterventionGraphOutcome(
        status="success",
        output_path=str(output_path),
        node_count=len(nodes),
        edge_count=len(edges),
        causa_count=sum(1 for node in nodes if node["kind"] == "causa"),
        estrategia_count=sum(1 for node in nodes if node["kind"] == "estrategia"),
        circuitos_sin_corrida=sin_corrida,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m chec_local_interpreter.intervention_graph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_command = subparsers.add_parser("build")
    build_command.add_argument("--sampled", nargs="+", required=True)
    build_command.add_argument("--output", required=True)
    build_command.add_argument("--runs-root", default=None)
    build_command.add_argument("--min-support", type=int, default=DEFAULT_MIN_SUPPORT)
    build_command.add_argument("--max-estrategias", type=int, default=DEFAULT_MAX_ESTRATEGIAS)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        outcome = build_intervention_graph(
            args.sampled,
            args.output,
            runs_root=args.runs_root,
            min_support=args.min_support,
            max_estrategias=args.max_estrategias,
        )
        print(outcome.to_json_text())
        return 0 if outcome.status in ("success", "skipped_empty") else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
