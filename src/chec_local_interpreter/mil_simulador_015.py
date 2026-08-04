"""Bag-level simulation on notebook 05's MIL model, for notebook 06.

Notebook 06's simulator originally scored the MGCECDL classifier ONE EVENT
ROW at a time and aggregated the probabilities per vano. The model notebook
05 trains is a different animal: it scores BAGS. One bag is one
`(circuito, vano, ventana)` cell, its instances are that vano's event rows
inside that window, and its criticality class comes from
`asignar_clase(OBSERVED n_obs, predicted u-hat)` on 01.4's own KMeans
geometry -- the SAME geometry the historical map paints with, which is why
both maps end up on one colour scale by construction rather than by
convention.

Two things this module deliberately does NOT do:

- It never uses `mil_vano_ventana.predict_fn`. That function pins the
  per-row SHAP/simulator contract by making every row a singleton bag with
  `n_obs = 1`. `n_obs` is an AXIS of the KMeans space that defines the
  class, so scoring that way would slide every vano along an axis the model
  does not predict, and the resulting map would disagree with the
  historical one for reasons that have nothing to do with the simulation.
- It never touches `n_obs`. An override changes instance FEATURES, which
  moves u-hat; the number of events stays observed, always
  (`BagPredictor.predict_class`'s own boundary, design D8).

The MIL instance matrix is RAW model space -- `construir_matriz_instancias`
stacks `procesar_dataset_completo`'s `X` with the COD_CAUSA block and no
min-max scaler runs afterwards. So an override is written straight into its
column once `_coerce_original_value_for_model` has resolved categories and
dates, with none of `simulate_explicit_overrides`'s scaler round trip.

See:
  - `chec_impacto/interpretability/mil_vano_ventana.py` (`BagPredictor`)
  - `chec_impacto/data/bags.py` (`BagIndex`, the CSR instance layout)
  - `chec_impacto/interpretability/mgcecdl_graph.py`
    (`grafo_reconstruido_por_grupo`, `estadistico_colapso`)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from chec_impacto.interpretability.mil_vano_ventana import grafo_por_grupo_si_no_colapsado
from chec_impacto.models.criticality_assignment import asignar_clase, distribucion_suave
from chec_local_interpreter.relevancias_015 import normalizar_softmax
from chec_local_interpreter.simulator import _coerce_original_value_for_model, _direction

MENSAJE_SIN_BOLSAS = "Sin bolsas (vano x ventana) para esta seleccion."


def seleccionar_bolsas(
    bag_index: Any,
    *,
    circuito: str,
    ventana: str,
    marcados: Iterable[str] = (),
) -> dict[str, Any]:
    """The bags of `circuito` inside window `ventana` (its 01.4 label, `"V1"`
    ... `"V11"`), restricted to `marcados` when it is non-empty.

    An EMPTY `marcados` means the whole circuit in that window -- the same
    grain the map, the relevance ranking and the KMeans cloud already fall
    back to, so the four panels never describe different vano sets.

    Returns the pieces a bag forward pass needs: `filas` (positions into the
    instance matrix, in CSR order), `instance_bag` RENUMBERED from 0 (the
    model's `n_bags` is `instance_bag.max() + 1`, so the original bag ids
    would allocate one empty bag per unselected cell), `n_obs` (observed
    event counts, never predicted) and `fid` in bag order.
    """
    keys = bag_index.keys
    mask = (
        (keys["CIRCUITO"].astype(str).to_numpy() == str(circuito))
        & (keys["VENTANA"].astype(str).to_numpy() == str(ventana))
    )
    marcados = {str(m) for m in marcados}
    if marcados:
        # `astype(str)`: los fids del mapa son strings y la columna puede venir
        # numerica -- sin coercion no coincide NINGUNO y la seleccion sale vacia
        # sin decir por que.
        mask = mask & np.isin(keys["FID_VANO"].astype(str).to_numpy(), list(marcados))

    bolsas = np.flatnonzero(mask)
    offsets = np.asarray(bag_index.offsets, dtype=np.int64)
    counts = np.asarray(bag_index.counts, dtype=np.int64)[bolsas]

    if bolsas.size == 0:
        vacio = np.array([], dtype=np.int64)
        return {"bolsas": bolsas, "filas": vacio, "instance_bag": vacio,
                "n_obs": vacio, "fid": [], "n_bolsas": 0}

    filas = np.concatenate([np.arange(offsets[b], offsets[b + 1]) for b in bolsas])
    instance_bag = np.repeat(np.arange(len(bolsas), dtype=np.int64), counts)
    return {
        "bolsas": bolsas,
        "filas": filas,
        "instance_bag": instance_bag,
        "n_obs": counts,
        "fid": [str(f) for f in keys["FID_VANO"].astype(str).to_numpy()[bolsas]],
        "n_bolsas": int(len(bolsas)),
    }


def aplicar_overrides_instancias(
    X_sel: np.ndarray,
    feature_names: Sequence[str],
    overrides: Sequence[Mapping[str, Any]],
    *,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> tuple[np.ndarray, list[str], list[str]]:
    """Write each override's value into its feature column, broadcast across
    every instance of the selection, on a COPY (the cached instance matrix is
    shared by every later call and must never be mutated).

    Values go through `_coerce_original_value_for_model`, the same resolver
    `simulate_explicit_overrides` uses for categories, dates and the NaN
    sentinel -- but with no scaler afterwards, because the MIL instance
    matrix is already raw model space.

    A failing override never raises: it is reported and every other override
    still applies (`simulate_explicit_overrides`'s own policy -- one bad knob
    should not throw away a simulation the user is waiting on). Returns
    `(X_simulada, variables_aplicadas, avisos)`.
    """
    X_sim = np.array(X_sel, dtype=np.float64, copy=True)
    posicion = {str(name): i for i, name in enumerate(feature_names)}
    aplicadas: list[str] = []
    avisos: list[str] = []

    for override in overrides:
        variable = str(override["variable"])
        indice = posicion.get(variable)
        if indice is None:
            avisos.append(f"Variable desconocida para el modelo MIL: {variable}")
            continue
        try:
            valor = _coerce_original_value_for_model(
                variable,
                override["valor"],
                label_encoders=dict(label_encoders or {}),
                max_values_imputed=dict(max_values_imputed or {}),
            )
        except (ValueError, TypeError) as exc:
            avisos.append(f"{variable}: {exc}")
            continue
        X_sim[:, indice] = valor
        aplicadas.append(variable)

    return X_sim, aplicadas, avisos


def simular_bolsas(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    seleccion: Mapping[str, Any],
    feature_names: Sequence[str],
    overrides: Sequence[Mapping[str, Any]],
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Two bag forward passes -- base and simulated -- over `seleccion`, and
    the KMeans class of each from `(observed n_obs, predicted u-hat)`.

    Column names match `simulate_explicit_overrides`'s schema
    (`FID_VANO`, `base_clase_idx`, `simulado_clase_idx`,
    `delta_riesgo_ordinal`) so the notebook's map painting -- and
    `vano_app_015.clases_por_fid_para_estado` -- read this table unchanged.

    An empty selection returns an empty table WITHOUT a forward pass: a map
    of fabricated classes over zero vanos is worse than an explicit blank.
    """
    if int(seleccion["n_bolsas"]) == 0:
        vacia = pd.DataFrame(
            columns=["FID_VANO", "u_base", "u_simulado", "base_clase_idx",
                     "simulado_clase_idx", "delta_riesgo_ordinal"]
        )
        return vacia, {"n_vanos": 0, "n_instancias": 0, "variables_aplicadas": [],
                       "avisos": []}

    filas = np.asarray(seleccion["filas"], dtype=np.int64)
    instance_bag = np.asarray(seleccion["instance_bag"], dtype=np.int64)
    n_obs = np.asarray(seleccion["n_obs"], dtype=np.float64)
    X_sel = np.asarray(X_inst, dtype=np.float64)[filas]

    X_sim, aplicadas, avisos = aplicar_overrides_instancias(
        X_sel, feature_names, overrides,
        label_encoders=label_encoders, max_values_imputed=max_values_imputed,
    )

    u_base = np.asarray(predictor.predict(X_sel, instance_bag=instance_bag), dtype=float)
    u_sim = np.asarray(predictor.predict(X_sim, instance_bag=instance_bag), dtype=float)

    clase_base, _ = asignar_clase(n_obs, u_base, predictor.geometria)
    clase_sim, _ = asignar_clase(n_obs, u_sim, predictor.geometria)

    tabla = pd.DataFrame(
        {
            "FID_VANO": [str(f) for f in seleccion["fid"]],
            "n_obs": n_obs.astype(int),
            "u_base": u_base,
            "u_simulado": u_sim,
            "base_clase_idx": np.asarray(clase_base, dtype=int),
            "simulado_clase_idx": np.asarray(clase_sim, dtype=int),
        }
    )
    tabla["delta_riesgo_ordinal"] = tabla["simulado_clase_idx"] - tabla["base_clase_idx"]

    metadata = {
        "n_vanos": int(len(tabla)),
        "n_instancias": int(len(filas)),
        "variables_aplicadas": aplicadas,
        "avisos": avisos,
    }
    return tabla, metadata


def _riesgo_ordinal(n_obs: np.ndarray, u: np.ndarray, geometria: Any) -> float:
    """Mean expected class index over the bags -- the SAME quantity
    `simulator._risk_score` measures for the MGCECDL panel (`probs @ [0..3]`,
    averaged), so the ranking's numbers keep meaning what they meant before
    the model swap. The hard reported class stays `asignar_clase`'s argmin;
    this soft distribution exists only to make the scenario difference a
    continuous number instead of a step."""
    distribucion = distribucion_suave(np.asarray(n_obs, dtype=float), np.asarray(u, dtype=float), geometria)
    eje_clases = np.arange(distribucion.shape[1], dtype=float)
    return float(np.mean(distribucion @ eje_clases))


def sensibilidad_minmax_bolsas(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    seleccion: Mapping[str, Any],
    feature_names: Sequence[str],
    knobs: Sequence[Any],
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
    tolerancia: float = 1e-6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Min/max sensitivity sweep at BAG grain, one row per numeric knob.

    Same shape as the MGCECDL panel it replaces (`relevancias_015`): each row
    carries `magnitud_max_cambio_abs = max(|delta_min|, |delta_max|)` over the
    selection's mean ordinal risk, so `normalizar_softmax` and the panel read
    it unchanged. What changes is the unit: the scenario is scored on the same
    bags the simulated map paints, not on individual event rows, so the panel
    and the map finally answer about the same thing.

    A knob's whole family moves together (`knob.feature_names`), which is the
    point of the catalog: a climate family's 12 lags are one control, not 12.
    Knobs without numeric bounds -- categorical and constant -- are SKIPPED,
    exactly as `simulate_automatic_minmax_sensitivity` skips a non-numeric
    column: inventing a range for them would score a scenario nobody asked
    for.

    Cost is `1 + 2 * n_knobs_numericos` bag forward passes: one shared
    baseline, and min/max per knob.
    """
    if int(seleccion["n_bolsas"]) == 0:
        return [], {"n_vanos": 0, "n_instancias": 0, "avisos": []}

    filas_idx = np.asarray(seleccion["filas"], dtype=np.int64)
    instance_bag = np.asarray(seleccion["instance_bag"], dtype=np.int64)
    n_obs = np.asarray(seleccion["n_obs"], dtype=float)
    X_base = np.asarray(X_inst, dtype=np.float64)[filas_idx]

    riesgo_base = _riesgo_ordinal(
        n_obs, predictor.predict(X_base, instance_bag=instance_bag), predictor.geometria
    )

    filas: list[dict[str, Any]] = []
    avisos: list[str] = []
    for knob in knobs:
        if knob.kind != "numeric" or not knob.bounds:
            continue
        minimo, maximo = (float(v) for v in knob.bounds)
        escenarios: dict[str, float] = {}
        for nombre, valor in (("minimo", minimo), ("maximo", maximo)):
            overrides = [{"variable": f, "valor": valor} for f in knob.feature_names]
            X_sim, aplicadas, avisos_knob = aplicar_overrides_instancias(
                X_base, feature_names, overrides,
                label_encoders=label_encoders, max_values_imputed=max_values_imputed,
            )
            avisos.extend(avisos_knob)
            if not aplicadas:
                continue
            escenarios[nombre] = _riesgo_ordinal(
                n_obs, predictor.predict(X_sim, instance_bag=instance_bag), predictor.geometria
            ) - riesgo_base
        if len(escenarios) != 2:
            continue
        filas.append(
            {
                "knob_id": knob.id,
                "label": knob.label,
                "magnitud_max_cambio_abs": float(
                    max(abs(escenarios["minimo"]), abs(escenarios["maximo"]))
                ),
                "direccion_maximo": _direction(escenarios["maximo"], tolerance=tolerancia),
                "direccion_minimo": _direction(escenarios["minimo"], tolerance=tolerancia),
            }
        )

    filas.sort(key=lambda fila: fila["magnitud_max_cambio_abs"], reverse=True)
    return filas, {
        "n_vanos": int(seleccion["n_bolsas"]),
        "n_instancias": int(len(filas_idx)),
        "riesgo_base": riesgo_base,
        "avisos": avisos,
    }


def construir_relevance_cache_mil(
    *,
    predictor: Any,
    X_inst: np.ndarray,
    bag_index: Any,
    feature_names: Sequence[str],
    knobs: Sequence[Any],
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
    maxsize: int = 32,
) -> Callable[[str, str, Iterable[str]], dict[str, Any]]:
    """Session-scoped LRU over `sensibilidad_minmax_bolsas`, keyed by
    `(circuito, ventana, marcados)` -- the drop-in replacement for
    `relevancias_015.construir_relevance_cache`, returning the same
    `{'vacio', 'filas', 'n_vanos', 'n_filas', 'mensaje'}` shape with
    softmax-normalised `relevancia` already on each row.

    No disk cache, unlike the MGCECDL version: that one persisted the
    all-vanos key because 53 row-level passes over a whole circuit were slow
    enough to be worth a file and its fingerprint. The bag sweep runs over
    tens of bags, so the LRU covers it and there is no stale-artifact surface
    to invalidate when the model is retrained.
    """
    marcados_vacio = "__TODOS__"

    @lru_cache(maxsize=maxsize)
    def _rankear(circuito: str, ventana: str, clave: Any) -> tuple[tuple[dict, ...], int, int]:
        marcados = () if clave == marcados_vacio else clave
        seleccion = seleccionar_bolsas(bag_index, circuito=circuito, ventana=ventana,
                                       marcados=marcados)
        filas, meta = sensibilidad_minmax_bolsas(
            predictor, X_inst, seleccion=seleccion, feature_names=feature_names,
            knobs=knobs, label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
        )
        return tuple(filas), int(meta["n_vanos"]), int(meta["n_instancias"])

    def rankear(circuito: str, ventana: str, marcados: Iterable[str]) -> dict[str, Any]:
        marcados_set = tuple(sorted({str(m) for m in marcados}))
        clave = marcados_vacio if not marcados_set else marcados_set
        filas, n_vanos, n_instancias = _rankear(str(circuito), str(ventana), clave)
        vacio = len(filas) == 0
        return {
            "vacio": vacio,
            "filas": normalizar_softmax([dict(fila) for fila in filas]),
            "n_vanos": n_vanos,
            "n_filas": n_instancias,
            "mensaje": MENSAJE_SIN_BOLSAS if vacio else None,
        }

    return rankear


def gates_de_bolsas(
    predictor: Any, X_sel: np.ndarray, instance_bag: np.ndarray, n_bags: int
) -> np.ndarray:
    """`(n_bags, n_edges)` edge gates from one forward pass. A thin torch
    adapter with no decisions in it -- everything downstream (`grafo_de_gates`)
    is pure and tested."""
    import torch

    predictor.model.eval()
    with torch.no_grad():
        x = torch.as_tensor(np.asarray(X_sel, dtype=np.float32), device=predictor.device)
        bolsas = torch.as_tensor(
            np.asarray(instance_bag, dtype=np.int64), dtype=torch.long, device=predictor.device
        )
        salida = predictor.model(x, bolsas, int(n_bags))
    return salida["edge_gates"].detach().cpu().numpy()


def grafo_de_gates(
    gate_means: np.ndarray, edge_index: Any, n_features: int
) -> dict[str, Any]:
    """ONE reconstructed expert graph for the whole selection: the fixed
    expert edge weights as this set of vanos actually uses them
    (`mean_vano(gate) * fixed_weight`).

    It is the per-group reconstruction of `mgcecdl_graph` called with a
    SINGLE label, so there is no new maths here -- the panel shows the
    selection's graph, not one graph per criticality tier, which would not
    fit a single panel and is not what "the graph of these vanos" means.

    A4 is respected through `grafo_por_grupo_si_no_colapsado`: a collapsed
    gate matrix VOIDS the graph instead of drawing one, because a gate that
    does not vary across vanos carries no per-selection structure and
    drawing it would present the fixed expert graph as if the selection had
    produced it. An empty selection is voided the same way, without calling
    the maths at all.
    """
    gate_means = np.asarray(gate_means, dtype=np.float64)
    if gate_means.size == 0 or gate_means.shape[0] == 0:
        return {"voided": True, "matriz": None, "n_vanos": 0, "colapso": None}

    resultado = grafo_por_grupo_si_no_colapsado(
        gate_means, edge_index, np.zeros(gate_means.shape[0], dtype=int), int(n_features)
    )
    if resultado["voided"]:
        return {"voided": True, "matriz": None, "n_vanos": int(gate_means.shape[0]),
                "colapso": resultado["colapso"]}

    grafo = resultado["grafos_por_grupo"][0]
    return {
        "voided": False,
        "matriz": np.asarray(grafo["matrix"], dtype=float),
        "n_vanos": int(grafo["n_vanos"]),
        "colapso": resultado["colapso"],
    }


def trazas_grafo(
    matriz: np.ndarray, feature_names: Sequence[str]
) -> dict[str, dict[str, list]]:
    """Circular layout for the reconstructed graph, ready to drop into three
    Plotly traces: `aristas` (one polyline per edge, `None`-separated so the
    segments do not join), `pesos` (one marker at each edge's midpoint, where
    the weight is readable -- a single line trace cannot vary its width per
    segment) and `nodos`.

    Only features that participate in at least one edge are laid out: the
    instance matrix has 80 columns and the expert graph has 64 edges over a
    fraction of them, so drawing every column would put a ring of isolated
    dots around the part that carries the information.
    """
    matriz = np.asarray(matriz, dtype=float)
    filas, columnas = np.nonzero(matriz)
    participantes = sorted(set(filas.tolist()) | set(columnas.tolist()))

    vacio = {
        "aristas": {"x": [], "y": []},
        "pesos": {"x": [], "y": [], "peso": [], "hovertext": []},
        "nodos": {"x": [], "y": [], "texto": [], "indice": []},
    }
    if not participantes:
        return vacio

    angulos = np.linspace(0.0, 2.0 * np.pi, len(participantes), endpoint=False)
    posicion = {
        nodo: (float(np.cos(a)), float(np.sin(a)))
        for nodo, a in zip(participantes, angulos)
    }

    arista_x: list[float | None] = []
    arista_y: list[float | None] = []
    peso_x: list[float] = []
    peso_y: list[float] = []
    pesos: list[float] = []
    hovertext: list[str] = []
    for origen, destino in zip(filas.tolist(), columnas.tolist()):
        x0, y0 = posicion[origen]
        x1, y1 = posicion[destino]
        arista_x.extend([x0, x1, None])
        arista_y.extend([y0, y1, None])
        peso_x.append((x0 + x1) / 2.0)
        peso_y.append((y0 + y1) / 2.0)
        peso = float(matriz[origen, destino])
        pesos.append(peso)
        hovertext.append(
            f"<b>{feature_names[origen]} &#8594; {feature_names[destino]}</b>"
            f"<br>Peso reconstruido: {peso:.4g}"
        )

    return {
        "aristas": {"x": arista_x, "y": arista_y},
        "pesos": {"x": peso_x, "y": peso_y, "peso": pesos, "hovertext": hovertext},
        "nodos": {
            "x": [posicion[n][0] for n in participantes],
            "y": [posicion[n][1] for n in participantes],
            "texto": [str(feature_names[n]) for n in participantes],
            # La posicion de columna viaja con el nodo: es lo que deja al cuaderno
            # agrupar cada variable por su MODALIDAD (climatica o estructural) sin
            # volver a resolver el nombre contra la lista de features.
            "indice": list(participantes),
        },
    }
