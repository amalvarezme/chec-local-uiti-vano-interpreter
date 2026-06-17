"""Expert graph helpers aligned with the processed CHEC feature matrix."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

import numpy as np


CLIMATE_FAMILIES = (
    "prep",
    "temp",
    "wind_gust_spd",
    "wind_spd",
    "clouds",
    "pres",
    "sp",
    "rh",
    "solar_rad",
)


def construir_aristas_grafo_chec(
    ventana_climatica_horas: int = 12,
) -> list[tuple[str, str, float]]:
    """Build the directed weighted expert graph used by the CHEC graph notebook."""
    edges: list[tuple[str, str, float]] = []
    for family in CLIMATE_FAMILIES:
        for hour in range(ventana_climatica_horas - 1, 0, -1):
            edges.append((f"{family}_{hour}", f"{family}_{hour - 1}", 0.90))
        edges.append((f"{family}_0", "COD_CAUSA", 0.85))

    edges.extend(
        [
            ("NR_T", "COD_CAUSA", 0.85),
            ("DDT", "COD_CAUSA", 0.90),
            ("wind_gust_spd_0", "NR_T", 0.80),
            ("CANTIDAD_TIERRA", "DDT", 0.85),
            ("NG_RED", "DDT", 0.75),
            ("LONGITUD", "COD_CAUSA", 0.70),
            ("CONDUCTOR", "COD_CAUSA", 0.80),
            ("ALTURA", "NR_T", 0.75),
            ("VAL_CRIT_APOYO", "NR_T", 0.60),
            ("CLASE", "VAL_CRIT_APOYO", 0.80),
            ("NORMA", "VAL_CRIT_APOYO", 0.80),
            ("X1", "FID_VANO", 1.0),
            ("Y1", "FID_VANO", 1.0),
            ("X2", "FID_VANO", 1.0),
            ("Y2", "FID_VANO", 1.0),
            ("FID_VANO", "LVSW", 0.90),
            ("CIRCUITO", "FID_VANO", 0.80),
            ("LVSW", "COD_EQ_PROTEGE", 0.85),
            ("CNT_VN", "COD_EQ_PROTEGE", 0.85),
            ("COD_EQ_PROTEGE", "FID_SW", 1.0),
            ("FID_SW", "TIPO", 0.90),
            ("TIPO", "DURACION", 0.85),
            ("TIPO", "T_USUS_EQ_PROT", 0.85),
            ("CNT_VN_SW", "T_USUS_EQ_PROT", 0.80),
            ("PORC_APORTE_VANO", "CNT_VN_SW", 0.70),
            ("COD_APOYO_FIN", "FID_APOYO_FIN", 1.0),
            ("PROPIETARIO", "FID_APOYO_FIN", 0.50),
            ("ELEMENTO", "FID_APOYO_FIN", 0.80),
            ("LONG_CRUCETA", "FID_APOYO_FIN", 0.70),
            ("FID_TRAFO", "CODIGO", 1.0),
            ("FID_APOYO_FIN", "FID_TRAFO", 0.90),
            ("CAPACIDAD_NOMINAL", "CNT_USUS", 0.85),
            ("FECHA_OPERACION_TRF", "FID_TRAFO", 0.60),
            ("PROMEDIO_KWH_TRF", "CNT_USUS", 0.80),
            ("CNT_USUS", "TOT_USUS", 0.90),
            ("CNT_TRF", "TOT_USUS", 0.85),
            ("PROMEDIO_KWH_VANO", "CNT_FASES", 0.70),
            ("CALIBRE_NEUTRO", "CONDUCTOR", 0.80),
            ("FECHA_OPERACION_VANO", "CONDUCTOR", 0.60),
            ("TIPO_TAX", "FID_VANO", 0.70),
            ("COD_CAUSA", "DESC_CAUSA", 1.0),
            ("COD_CAUSA", "FECHA", 0.70),
            ("FECHA", "UITI_VANO", 0.70),
            ("T_USUS_EQ_PROT", "TOT_USUS", 0.95),
            ("DURACION", "UITI", 1.0),
            ("TOT_USUS", "UITI", 1.0),
            ("UITI", "UITI_VANO", 1.0),
            ("PORC_APORTE_VANO", "UITI_VANO", 1.0),
        ]
    )
    return edges


def _registrar_arista_preservada(
    preserved_edges: dict[tuple[str, str], dict[str, object]],
    source: str,
    target: str,
    weight: float,
    path: list[str],
    is_virtual: bool,
) -> None:
    if source == target:
        return

    key = (source, target)
    current = preserved_edges.get(key)
    candidate = {
        "source": source,
        "target": target,
        "weight": float(weight),
        "path": path,
        "is_virtual": is_virtual,
    }
    if current is None:
        preserved_edges[key] = candidate
        return
    if bool(current["is_virtual"]) and not is_virtual:
        preserved_edges[key] = candidate
        return
    if bool(current["is_virtual"]) == is_virtual and weight > float(current["weight"]):
        preserved_edges[key] = candidate


def construir_aristas_preservadas(
    edges: Sequence[tuple[str, str, float]],
    kept_nodes: Sequence[str],
) -> list[dict[str, object]]:
    """Preserve directed connectivity through nodes removed by feature selection."""
    kept_nodes_set = set(kept_nodes)
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for source, target, weight in edges:
        adjacency.setdefault(source, []).append((target, float(weight)))

    preserved_edges: dict[tuple[str, str], dict[str, object]] = {}
    for source in kept_nodes:
        queue: deque[tuple[str, list[str], float]] = deque()
        visited_removed: set[str] = set()

        for target, weight in adjacency.get(source, []):
            if target in kept_nodes_set:
                _registrar_arista_preservada(
                    preserved_edges, source, target, weight, [source, target], False
                )
            else:
                queue.append((target, [source, target], weight))

        while queue:
            current_node, path, path_weight = queue.popleft()
            if current_node in kept_nodes_set:
                _registrar_arista_preservada(
                    preserved_edges,
                    source,
                    current_node,
                    path_weight,
                    path,
                    True,
                )
                continue
            if current_node in visited_removed:
                continue
            visited_removed.add(current_node)

            for next_node, edge_weight in adjacency.get(current_node, []):
                queue.append(
                    (
                        next_node,
                        [*path, next_node],
                        min(path_weight, edge_weight),
                    )
                )

    return list(preserved_edges.values())


def construir_matriz_adyacencia_mgcecdl(
    features: Sequence[str],
    ventana_climatica_horas: int = 12,
) -> tuple[np.ndarray, list[dict[str, object]]]:
    """Return a directed adjacency matrix aligned exactly with ``features`` order."""
    feature_list = list(features)
    if len(feature_list) != len(set(feature_list)):
        raise ValueError("features contiene nombres duplicados.")

    preserved_edges = construir_aristas_preservadas(
        construir_aristas_grafo_chec(ventana_climatica_horas),
        feature_list,
    )
    positions = {feature: index for index, feature in enumerate(feature_list)}
    matrix = np.zeros((len(feature_list), len(feature_list)), dtype=np.float32)
    for edge in preserved_edges:
        source = str(edge["source"])
        target = str(edge["target"])
        matrix[positions[source], positions[target]] = float(edge["weight"])

    return matrix, preserved_edges
