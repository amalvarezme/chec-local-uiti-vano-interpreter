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
from chec_local_interpreter.vano_controls import (
    VALORES_NO_VALIDOS,
    expand_knob_overrides,
)

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


def _filas_por_fid(
    instance_bag: np.ndarray, fids: Sequence[str]
) -> dict[str, np.ndarray]:
    """Boolean row mask per vano. A selection is ONE window, so a fid should
    own a single bag -- but if it ever owns two, writing into only one of them
    would leave half the simulation silently unapplied, so every bag with that
    fid contributes."""
    instance_bag = np.asarray(instance_bag)
    por_fid: dict[str, np.ndarray] = {}
    for bolsa, fid in enumerate(fids):
        mascara = instance_bag == bolsa
        clave = str(fid)
        por_fid[clave] = mascara if clave not in por_fid else (por_fid[clave] | mascara)
    return por_fid


def valores_actuales_por_vano(
    X_sel: np.ndarray,
    feature_names: Sequence[str],
    *,
    instance_bag: np.ndarray,
    fids: Sequence[str],
    knobs: Iterable[Any],
    label_encoders: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Where each vano's controls should START: that vano's OWN value in the
    active window, one entry per knob, keyed `{fid: {knob_id: valor}}`.

    A control that opens at a global default quietly asks the user to retype
    data the model already holds, and -- worse -- any control left untouched
    would then simulate the vano at a value that was never its own.

    A vano usually brings several instances inside one window (its event rows),
    so the value has to be summarised:

    - numeric knobs take the MEDIAN. The mean is dragged by the storm hour
      that motivated the row in the first place, which would open the control
      already displaced towards the extreme.
    - a climate family takes the median over ALL of its 12 lag columns pooled,
      because the control writes ONE value into the twelve at once: summarising
      only lag 0 would start it at a number the control itself cannot hold.
    - categorical knobs take the MODE, decoded back to its label. A median over
      label codes can land on a code the vano never had -- between `A`=0 and
      `C`=2 it returns 1, which is `B`. Ties break towards the lowest code so
      the panel opens the same way on every run; a control that starts
      somewhere different each time makes two simulations incomparable.

    Constant knobs get nothing (they have nothing to move), and a knob whose
    feature is absent from `feature_names` is skipped rather than raised: the
    MIL instance matrix carries more columns than the knob catalogue and a
    mismatch must not take down the whole panel at startup.
    """
    label_encoders = dict(label_encoders or {})
    X_sel = np.asarray(X_sel, dtype=float)
    posicion = {str(name): i for i, name in enumerate(feature_names)}
    por_fid = _filas_por_fid(instance_bag, fids)

    valores: dict[str, dict[str, Any]] = {}
    for fid, mascara in por_fid.items():
        del_vano: dict[str, Any] = {}
        if X_sel.size and mascara.any():
            for knob in knobs:
                if knob.kind == "constant":
                    continue
                columnas = [posicion[n] for n in knob.feature_names if n in posicion]
                if not columnas:
                    continue
                bloque = X_sel[np.ix_(mascara, columnas)]
                if knob.kind == "numeric":
                    # Un codigo de relleno no es un valor: contarlo en la mediana
                    # abre el control en un numero que ese vano nunca tuvo -- y que
                    # ni siquiera cae dentro de los limites del propio control, que
                    # ya lo excluyeron. Sin ningun valor real la clave se omite, y
                    # el panel puede decir que no hay dato en vez de inventarlo.
                    rellenos = VALORES_NO_VALIDOS.get(str(knob.feature_names[0]))
                    if rellenos:
                        bloque = bloque[~np.isin(bloque, list(rellenos))]
                        if bloque.size == 0:
                            continue
                if knob.kind == "categorical":
                    codigos, cuentas = np.unique(bloque.astype(np.int64), return_counts=True)
                    # `argmax` se queda con el PRIMERO en caso de empate, y `unique`
                    # devuelve ordenado: el desempate cae en el codigo mas bajo.
                    codigo = int(codigos[int(np.argmax(cuentas))])
                    del_vano[knob.id] = _etiqueta_de_codigo(
                        knob, codigo, label_encoders.get(str(knob.feature_names[0]))
                    )
                else:
                    del_vano[knob.id] = float(np.median(bloque))
        valores[fid] = del_vano
    return valores


def _etiqueta_de_codigo(knob: Any, codigo: int, encoder: Any) -> Any:
    """El control muestra ETIQUETAS, no codigos. Se prefiere el `classes_` del
    encoder, que es la fuente que uso el entrenamiento; si no esta, se cae a las
    categorias del propio knob, y si el codigo se sale de rango se devuelve el
    codigo crudo antes que inventar una categoria."""
    clases = getattr(encoder, "classes_", None)
    if clases is None:
        clases = knob.categories
    if clases is not None and 0 <= codigo < len(clases):
        return clases[codigo]
    return codigo


def aplicar_overrides_por_vano(
    X_sel: np.ndarray,
    feature_names: Sequence[str],
    overrides_por_vano: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    instance_bag: np.ndarray,
    fids: Sequence[str],
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> tuple[np.ndarray, list[str], list[str]]:
    """`aplicar_overrides_instancias`, but each vano gets its OWN value, written
    only into its own instance rows.

    The broadcast version answers "what if it rained 40 mm on all of them",
    which is the right question for a weather scenario and the wrong one for
    maintenance: pruning is scheduled vano by vano, and there was no way to say
    "raise the grounding of this one and leave the other four alone". Writing
    per-vano values through the broadcast path would let the last vano's value
    overwrite everyone else's.

    Same failure policy as the broadcast version: a control that cannot be
    resolved is reported and every other one still applies, because discarding
    a simulation the user is waiting on is worse than a partial answer that
    says what it skipped. An override aimed at a vano outside the selection --
    left over from a previous one -- is reported too, instead of landing
    nowhere in silence while the panel still shows its control.

    Returns `(X_simulada, variables_aplicadas, avisos)` with the variables
    reported ONCE and sorted: with five vanos the same variable arrives up to
    five times, and the panel's summary says WHAT moved, not how many cells
    were written.
    """
    X_sim = np.array(X_sel, dtype=np.float64, copy=True)
    posicion = {str(name): i for i, name in enumerate(feature_names)}
    por_fid = _filas_por_fid(instance_bag, fids)
    aplicadas: set[str] = set()
    avisos: list[str] = []

    for fid, overrides in overrides_por_vano.items():
        mascara = por_fid.get(str(fid))
        if mascara is None:
            avisos.append(
                f"El vano {fid} no esta en la seleccion activa: sus controles no se "
                "aplicaron."
            )
            continue
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
                avisos.append(f"{fid} / {variable}: {exc}")
                continue
            X_sim[mascara, indice] = valor
            aplicadas.add(variable)

    return X_sim, sorted(aplicadas), avisos


def simular_bolsas(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    seleccion: Mapping[str, Any],
    feature_names: Sequence[str],
    overrides: Sequence[Mapping[str, Any]] | None = None,
    overrides_por_vano: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Two bag forward passes -- base and simulated -- over `seleccion`, and
    the KMeans class of each from `(observed n_obs, predicted u-hat)`.

    Column names match `simulate_explicit_overrides`'s schema
    (`FID_VANO`, `base_clase_idx`, `simulado_clase_idx`,
    `delta_riesgo_ordinal`) so the notebook's map painting -- and
    `vano_app_015.clases_por_fid_para_estado` -- read this table unchanged.

    Overrides come in ONE of two shapes, never both:

    - `overrides`: one value per variable, broadcast over every instance of
      the selection. The right shape for a weather scenario -- "what if it
      rained 40 mm on all of them" is a single question about a single sky.
    - `overrides_por_vano`: `{fid: [{variable, valor}]}`, each written only
      into that vano's rows. The right shape for maintenance, which is
      scheduled vano by vano.

    Passing both raises. Accepting both would force inventing a precedence,
    and whichever one lost would leave the panel displaying a control that
    never reached the model.

    Either way it costs exactly TWO forward passes -- base and simulated --
    and never one per vano: the per-vano values are written into one matrix
    and scored together.

    An empty selection returns an empty table WITHOUT a forward pass: a map
    of fabricated classes over zero vanos is worse than an explicit blank.
    """
    if overrides and overrides_por_vano:
        raise ValueError(
            "Se recibieron overrides globales y por vano a la vez. Elegir uno: "
            "mezclarlos obliga a inventar una precedencia y deja controles del "
            "panel sin aplicar."
        )
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
    # Se INDEXA y despues se promueve, nunca al reves. `X_inst` es la matriz
    # completa del artefacto -- 288.632 x 80 en float32 -- y una seleccion son unos
    # cientos de filas: promoverla entera reserva y tira 176,7 MB en cada pasada,
    # contra 0,6 MB indexando primero, con el mismo resultado bit a bit. Ademas la
    # app de Databricks la carga MAPEADA en memoria, y promoverla entera la leeria
    # entera del disco y haria privada una copia que estaba compartida.
    X_sel = np.asarray(X_inst[filas], dtype=np.float64)

    if overrides_por_vano:
        X_sim, aplicadas, avisos = aplicar_overrides_por_vano(
            X_sel, feature_names, overrides_por_vano,
            instance_bag=instance_bag, fids=seleccion["fid"],
            label_encoders=label_encoders, max_values_imputed=max_values_imputed,
        )
    else:
        X_sim, aplicadas, avisos = aplicar_overrides_instancias(
            X_sel, feature_names, overrides or (),
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
        # Las features ya simuladas viajan de vuelta: el grafo `|base - simulado|` de
        # la ultima fila del 06 necesita este lado, y rearmarlo en el cuaderno seria
        # repetir la expansion de overrides -- la forma segura de que el grafo acabe
        # describiendo un escenario distinto del que puntuo el mapa.
        "X_simulado": X_sim,
    }
    return tabla, metadata


def clase_base_de_bolsas(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    seleccion: Mapping[str, Any],
) -> pd.DataFrame:
    """El estado BASE de una seleccion: `FID_VANO`, `u_base` y `base_clase_idx`.

    UNA pasada del modelo, no dos. `simular_bolsas` sin overrides devuelve exactamente
    esto y es lo que se usaba, pero de paso copia la matriz de la seleccion y la puntua
    otra vez para obtener el mismo numero. Con un solo mapa daba igual; el informe
    recorre TODAS las ventanas del circuito con su deslizador, y ahi el desperdicio se
    multiplica por once.

    Las columnas se llaman igual que en `simular_bolsas` a proposito: quien lee la tabla
    base no tiene que aprender un segundo vocabulario para las mismas dos cifras.

    Una seleccion vacia devuelve una tabla vacia SIN pasar por el modelo: puntuar cero
    bolsas produce una tabla de clases inventadas sobre ningun vano.
    """
    if int(seleccion.get("n_bolsas", 0)) == 0:
        return pd.DataFrame(columns=["FID_VANO", "n_obs", "u_base", "base_clase_idx"])

    filas = np.asarray(seleccion["filas"], dtype=np.int64)
    instance_bag = np.asarray(seleccion["instance_bag"], dtype=np.int64)
    n_obs = np.asarray(seleccion["n_obs"], dtype=np.float64)
    # Se INDEXA y despues se promueve, por la misma razon que en `simular_bolsas`:
    # promover `X_inst` entera reserva y tira cientos de MB en cada pasada.
    X_sel = np.asarray(X_inst[filas], dtype=np.float64)

    u_base = np.asarray(predictor.predict(X_sel, instance_bag=instance_bag), dtype=float)
    clase_base, _ = asignar_clase(n_obs, u_base, predictor.geometria)

    return pd.DataFrame(
        {
            "FID_VANO": [str(f) for f in seleccion["fid"]],
            "n_obs": n_obs.astype(int),
            "u_base": u_base,
            "base_clase_idx": np.asarray(clase_base, dtype=int),
        }
    )


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


def _riesgo_ordinal_por_bolsa(n_obs: np.ndarray, u: np.ndarray, geometria: Any) -> np.ndarray:
    """`_riesgo_ordinal` SIN promediar: el indice de clase esperado de cada bolsa.

    Es lo que permite que un solo barrido sirva para los cinco vanos. Cada pasada
    del modelo ya produce un u-hat por bolsa; promediarlo de inmediato tira esa
    informacion y obliga a repetir el barrido vano por vano.
    """
    distribucion = distribucion_suave(
        np.asarray(n_obs, dtype=float), np.asarray(u, dtype=float), geometria
    )
    eje_clases = np.arange(distribucion.shape[1], dtype=float)
    return np.asarray(distribucion @ eje_clases, dtype=float)


def sensibilidad_minmax_por_vano(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    seleccion: Mapping[str, Any],
    feature_names: Sequence[str],
    knobs: Sequence[Any],
    top: int = 5,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
    tolerancia: float = 1e-6,
) -> dict[str, list[dict[str, Any]]]:
    """El top `top` de variables mas relevantes PARA CADA VANO de la seleccion,
    como `{fid: [{knob_id, label, magnitud, direccion_maximo, direccion_minimo}]}`
    ordenado de mayor a menor.

    El panel mostraba un solo ranking, el de la seleccion entera. Con hasta cinco
    vanos bajo estudio eso contesta la pregunta equivocada: dice que variable mueve
    AL GRUPO, cuando la decision de mantenimiento necesita saber cual mueve a ESTE
    vano, el de la orden de trabajo que se esta costeando.

    Cuesta las MISMAS `1 + 2 * knobs_numericos` pasadas que el barrido agregado, no
    una tanda por vano. Cada pasada ya devuelve un u-hat por bolsa, asi que basta
    con no promediarlo (`_riesgo_ordinal_por_bolsa`). Escrito como un bucle sobre
    vanos serian cinco veces mas pasadas y el boton dejaria de sentirse inmediato.

    Los knobs sin limites numericos -- categoricos y constantes -- se SALTAN, igual
    que en el barrido agregado: inventarles un rango puntuaria un escenario que
    nadie pidio.
    """
    if int(seleccion["n_bolsas"]) == 0:
        return {}

    filas_idx = np.asarray(seleccion["filas"], dtype=np.int64)
    instance_bag = np.asarray(seleccion["instance_bag"], dtype=np.int64)
    n_obs = np.asarray(seleccion["n_obs"], dtype=float)
    fids = [str(f) for f in seleccion["fid"]]
    X_base = np.asarray(X_inst[filas_idx], dtype=np.float64)

    base = _riesgo_ordinal_por_bolsa(
        n_obs, predictor.predict(X_base, instance_bag=instance_bag), predictor.geometria
    )

    # magnitudes[knob] -> vector por bolsa
    columnas: list[tuple[Any, np.ndarray]] = []
    for knob in knobs:
        if knob.kind != "numeric" or not knob.bounds:
            continue
        minimo, maximo = (float(v) for v in knob.bounds)
        deltas: dict[str, np.ndarray] = {}
        for nombre, valor in (("minimo", minimo), ("maximo", maximo)):
            overrides = [{"variable": f, "valor": valor} for f in knob.feature_names]
            X_sim, aplicadas, _avisos = aplicar_overrides_instancias(
                X_base, feature_names, overrides,
                label_encoders=label_encoders, max_values_imputed=max_values_imputed,
            )
            if not aplicadas:
                continue
            deltas[nombre] = _riesgo_ordinal_por_bolsa(
                n_obs, predictor.predict(X_sim, instance_bag=instance_bag),
                predictor.geometria,
            ) - base
        if len(deltas) != 2:
            continue
        columnas.append((knob, deltas))

    por_vano: dict[str, list[dict[str, Any]]] = {}
    for b, fid in enumerate(fids):
        filas = [
            {
                "knob_id": knob.id,
                "label": knob.label,
                "magnitud": float(max(abs(deltas["minimo"][b]), abs(deltas["maximo"][b]))),
                "direccion_maximo": _direction(float(deltas["maximo"][b]), tolerance=tolerancia),
                "direccion_minimo": _direction(float(deltas["minimo"][b]), tolerance=tolerancia),
            }
            for knob, deltas in columnas
        ]
        filas.sort(key=lambda fila: fila["magnitud"], reverse=True)
        # Un fid repetido -- no deberia pasar en una sola ventana -- se queda con su
        # primera bolsa en vez de pisarse en silencio.
        por_vano.setdefault(fid, filas[:top])
    return por_vano


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
    X_base = np.asarray(X_inst[filas_idx], dtype=np.float64)

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


def grafo_diferencia(
    gates_base: np.ndarray,
    gates_simuladas: np.ndarray,
    edge_index: Any,
    n_features: int,
) -> dict[str, Any]:
    """`|graph(base) - graph(simulated)|`: how much the simulation moved each
    relation of the reconstructed expert graph.

    The panel used to show the selection's graph as it is. That graph is mostly
    the FIXED expert weights -- the gates only rescale them -- so the before and
    the after look the same side by side and the effect of the intervention, which
    is the whole point of the panel, is invisible. The difference isolates exactly
    what changed.

    ABSOLUTE and not signed: the question is how much a relation moved, not in
    which direction. An edge the intervention weakens and one it strengthens both
    say the same thing -- the intervention reached that relation.

    Voided when EITHER side is voided. Subtracting against a graph that could not
    be estimated would still produce a matrix, and that matrix would look like a
    result. `estadistico_colapso` voids below three vanos by construction, and the
    difference inherits it rather than working around it.

    An all-zero matrix is a RESULT and not an empty panel: it says the simulation
    did not move a single relation.
    """
    base = grafo_de_gates(gates_base, edge_index, n_features)
    simulado = grafo_de_gates(gates_simuladas, edge_index, n_features)
    if base["voided"] or simulado["voided"]:
        anulado = base if base["voided"] else simulado
        return {"voided": True, "matriz": None, "n_vanos": anulado["n_vanos"],
                "colapso": anulado["colapso"]}
    return {
        "voided": False,
        "matriz": np.abs(base["matriz"] - simulado["matriz"]),
        "n_vanos": base["n_vanos"],
        "colapso": base["colapso"],
    }


def plegar_rezagos(
    matriz: np.ndarray, feature_names: Sequence[str]
) -> tuple[np.ndarray, list[str]]:
    """Colapsa cada familia de rezagos en UN nodo, y devuelve la matriz y los nombres.

    El grafo del cuaderno 06 dibujaba 66 nodos, y 48 eran los doce rezagos de cuatro
    variables de clima. Con solo 64 aristas, ese anillo era casi todo decoracion: 13,6 px
    de arco por nombre para una fuente de 10 px, o sea nombres encimados. Plegado quedan
    22 nodos y 62,7 px de arco, y el radio sube de 142,9 a 219,4 px porque los rotulos
    dejan de comerse el rango del eje.

    Una familia es `<nombre>_<numero>`: `temp_0 .. temp_11` son `temp`. El sufijo tiene
    que ser TODO digitos -- `X2` y `TIPO_TAX` no son rezagos, y recortarlos por el ultimo
    `_` los volveria `X` y `TIPO`, fundiendo `TIPO_TAX` con la variable `TIPO`, que existe
    aparte.

    La relacion entre dos familias se queda con el MAXIMO de las relaciones entre sus
    miembros, no con la suma: sumar 144 pares de rezagos contra el unico par de dos
    variables estaticas haria que el clima dominara por contar mas, no por moverse mas.

    Las aristas DENTRO de una familia se descartan -- quedarian como un lazo de un nodo a
    si mismo, que en una disposicion circular es un punto --, asi que la diagonal sale en
    cero.
    """
    matriz = np.asarray(matriz, dtype=float)

    def _familia(nombre: str) -> str:
        cabeza, _, cola = str(nombre).rpartition("_")
        return cabeza if cabeza and cola.isdigit() else str(nombre)

    familias: list[str] = []
    indice_de: dict[str, int] = {}
    for nombre in feature_names:
        familia = _familia(nombre)
        if familia not in indice_de:
            indice_de[familia] = len(familias)
            familias.append(familia)

    destino = [indice_de[_familia(n)] for n in feature_names]
    plegada = np.zeros((len(familias), len(familias)), dtype=float)
    for i, fi in enumerate(destino):
        for j, fj in enumerate(destino):
            if fi == fj:
                continue
            plegada[fi, fj] = max(plegada[fi, fj], abs(float(matriz[i, j])))
    return plegada, familias


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


# --- Relevancia orientada al grupo BAJO (reemplaza al barrido min-max del panel) --------

REJILLA_UMBRAL_U = 1024
"""Cuantos puntos se prueban al buscar el `u` que hace caer una bolsa en el grupo mas bajo.

Rejilla y no biseccion: la clase sale del centroide MAS CERCANO en un plano, y nada
garantiza que al subir `u` con `n_obs` fijo se recorran los grupos en orden. Una
biseccion asume esa monotonia; una rejilla no asume nada y cuesta una llamada
vectorizada. Mil puntos sobre diez ordenes de magnitud dan una resolucion de ~2,3% en
`u`, muy por debajo de lo que separa a dos grupos.
"""


def umbral_u_para_clase_minima(
    n_obs: float, geometria: Any, *, puntos: int = REJILLA_UMBRAL_U
) -> float | None:
    """El `u` mas alto con el que una bolsa de `n_obs` eventos cae en el grupo MAS BAJO,
    o None si con esos eventos ese grupo es inalcanzable.

    Es el numero que convierte un ranking en una instruccion. "Esta variable baja el
    UITI un 70%" no es una respuesta: la pregunta de mantenimiento es si eso cambia de
    grupo, y para saberlo hace falta la meta.

    `n_obs` no se simula NUNCA -- es el otro eje del espacio que define la clase --, asi
    que la meta se calcula con los eventos observados y solo se mueve `u`. Medido sobre
    la geometria real de 01.4, el umbral se desploma cuando los eventos se acumulan: 4,41
    con un evento y 0,0029 con cuarenta y seis. Un vano con muchos eventos necesita un
    UITI casi nulo para bajar de grupo, y eso es una propiedad del espacio, no del panel.

    None y no un numero inventado: una meta que el simulador no puede cumplir se
    presentaria en el panel como alcanzable.
    """
    return umbral_u_para_clase(n_obs, geometria, 0, puntos=puntos)


def umbral_u_para_clase(
    n_obs: float, geometria: Any, clase: int, *, puntos: int = REJILLA_UMBRAL_U
) -> float | None:
    """El `u` mas alto con el que una bolsa de `n_obs` eventos cae en `clase`, o None.

    Generaliza `umbral_u_para_clase_minima`, que solo sabia preguntar por el grupo mas
    bajo. Hace falta porque el objetivo del plan es una ESCALERA: se apunta a Bajo, y
    cuando Bajo no existe para esa cantidad de eventos, se apunta al grupo de abajo del
    suyo. Sin esta version, un vano al que Bajo le queda fuera por construccion se
    quedaba sin meta y gastaba las cuatro rondas persiguiendo algo imposible.

    Rejilla y no biseccion, por la misma razon de siempre: la clase sale del centroide
    MAS CERCANO en un plano y nada garantiza que al subir `u` con `n_obs` fijo se
    recorran los grupos en orden.
    """
    rejilla = np.concatenate([[0.0], np.logspace(-6, 4, int(puntos))])
    clases, _ = asignar_clase(
        np.full(len(rejilla), float(n_obs)), rejilla, geometria
    )
    clases = np.asarray(clases)
    objetivo = int(clase)
    if not (clases == objetivo).any():
        return None
    return float(rejilla[clases == objetivo].max())


def candidatos_de_knob(
    knob: Any, *, puntos: int = 9, catalogo: Mapping[str, Any] | None = None
) -> list[Any] | None:
    """Los valores que se le prueban a un control, o None si no tiene ninguno.

    Con `catalogo` -- el de `Variables_simular.xlsx` -- manda lo que el PANEL ofrece, que
    es lo unico que se puede ejecutar. Sin el se cae a lo OBSERVADO en la base: un
    control numerico aporta una rejilla sobre su rango y uno categorico sus categorias.

    Ese respaldo no es el caso normal: es lo que mantiene vivo a quien llame sin
    catalogo -- pruebas con knobs a mano, y las familias climaticas, que no tienen
    entrada propia. Cuando los dos coincidian daba igual cual se usara; con el archivo
    ajustado dejaron de coincidir, y el diagnostico llego a proponer "2,37 fases".
    Ver `simulador_variables.candidatos_del_panel`.

    Los constantes quedan fuera en los dos casos: un unico valor observado no mueve nada,
    y probarlo solo gasta una pasada del modelo.
    """
    if catalogo is not None:
        from chec_local_interpreter.simulador_variables import candidatos_del_panel

        if knob.kind == "constant":
            return None
        valores = candidatos_del_panel(knob, catalogo.get(knob.id), puntos=puntos)
        return valores or None

    if knob.kind == "numeric" and knob.bounds:
        minimo, maximo = (float(v) for v in knob.bounds)
        return [float(v) for v in np.linspace(minimo, maximo, int(puntos))]
    if knob.kind == "categorical" and knob.categories:
        return list(knob.categories)
    return None


def _top_con_cuota(
    filas: list[dict[str, Any]], *, top: int, grupos: Mapping[str, str] | None
) -> list[dict[str, Any]]:
    """Las `top` mejores, reservando sitio para cada grupo de variables.

    Sin reserva, un ranking copado por las cuatro familias climaticas no deja ni una
    palanca que una cuadrilla pueda ejecutar -- y el panel existe para sostener una orden
    de trabajo. La reserva es la mitad para cada grupo; lo que un grupo no llene lo ocupa
    el otro por orden global, asi que nunca se desperdicia un sitio.

    Sin `grupos` se comporta como un top simple: la reserva es una decision del llamador
    y no algo que este modulo imponga.
    """
    if not grupos:
        return filas[:top]
    nombres = [g for g in dict.fromkeys(grupos.values()) if g]
    if len(nombres) < 2:
        return filas[:top]
    cuota = max(1, top // len(nombres))
    elegidas: list[dict[str, Any]] = []
    vistos: set[int] = set()
    for nombre in nombres:
        for fila in filas:
            if len(elegidas) >= top:
                break
            if fila.get("grupo") == nombre and id(fila) not in vistos:
                if sum(1 for f in elegidas if f.get("grupo") == nombre) >= cuota:
                    break
                elegidas.append(fila)
                vistos.add(id(fila))
    for fila in filas:                      # el resto, por orden global
        if len(elegidas) >= top:
            break
        if id(fila) not in vistos:
            elegidas.append(fila)
            vistos.add(id(fila))
    elegidas.sort(key=lambda f: f["caida_log"], reverse=True)
    return elegidas


def relevancia_hacia_uiti_minimo(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    seleccion: Mapping[str, Any],
    feature_names: Sequence[str],
    knobs: Sequence[Any],
    top: int = 10,
    puntos: int = 9,
    grupos: Mapping[str, str] | None = None,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
    catalogo: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Que variables pueden llevar a CADA vano a su UITI minimo, y cuanto lo bajan.

    Sustituye al barrido min-max del panel, que tenia dos defectos para la pregunta que
    de verdad se hace -- *que muevo para que este vano baje de grupo*:

    - Su magnitud era `max(|delta-|, |delta+|)`, SIN SIGNO. Una variable que dispara el
      riesgo en los dos extremos ganaba a una que lo baja un poco, y la cabeza del
      ranking se llenaba de palancas que no hay que tocar.
    - Solo miraba los dos EXTREMOS. Medido sobre el modelo real, 10 de los 15 controles
      numericos tienen su mejor valor en el INTERIOR del rango para alguna bolsa
      (`DDT` para todas): el modelo es marcadamente no monotono y los extremos son,
      simplemente, los dos puntos equivocados.

    Aqui cada control se recorre en una rejilla de `puntos` valores sobre su rango
    observado, se guarda el que MINIMIZA el u-hat de cada bolsa, y se ordena por cuanto
    lo baja. La caida se mide en ORDENES DE MAGNITUD de `u` -- el eje que usa la
    geometria KMeans -- y no en unidades: `u` recorre varios ordenes entre vanos, y en
    unidades el ranking de un vano caro seria incomparable con el de uno barato.

    Cada fila trae el VALOR que consigue ese minimo, asi que el ranking se lee como una
    instruccion ("lleva ALTURA a 25 m") y no como un puntaje. Y trae `alcanza`: si ese
    solo cambio basta para caer en el grupo mas bajo. Cuando ninguna lo logra -- medido,
    le pasa a un vano de Medio-Alto con u=271 -- decirlo vale mas que un ranking que
    insinua lo contrario.

    Cuesta `1 + puntos * K` pasadas para TODA la seleccion, no una tanda por vano: cada
    pasada ya devuelve un u-hat por bolsa. Medido sobre el modelo real, 15 controles a 9
    puntos son 136 pasadas en 0,2 s.

    Se recorren TODOS los controles que el panel ofrece, tambien los categoricos: su
    "rejilla" son sus categorias. Dejarlos fuera -- como hacia el barrido anterior --
    quitaba del ranking al conductor, al calibre del neutro y al tipo de proteccion, que
    son tres de las obras que CHEC efectivamente ejecuta; el usuario perdia libertad
    justo sobre la mitad de intervencion. Solo quedan fuera los constantes, que tienen un
    unico valor observado y no mueven nada.

    Con `grupos` (`knob_id -> "Intervencion" | "Escenario"`), el top RESERVA sitio para
    los dos: un ranking copado por las cuatro familias climaticas no deja ni una palanca
    que una cuadrilla pueda ejecutar, y al reves deja al panel sin la pregunta "que pasa
    si". La reserva es la mitad de `top` para cada grupo, y lo que un grupo no llene lo
    ocupa el otro por orden global.
    """
    if int(seleccion["n_bolsas"]) == 0:
        return {}

    filas_idx = np.asarray(seleccion["filas"], dtype=np.int64)
    instance_bag = np.asarray(seleccion["instance_bag"], dtype=np.int64)
    n_obs = np.asarray(seleccion["n_obs"], dtype=float)
    fids = [str(f) for f in seleccion["fid"]]
    X_base = np.asarray(X_inst[filas_idx], dtype=np.float64)

    u_base = np.asarray(predictor.predict(X_base, instance_bag=instance_bag), dtype=float)
    clase_base, _ = asignar_clase(n_obs, u_base, predictor.geometria)
    clase_base = np.asarray(clase_base, dtype=int)

    # Por knob: el mejor u alcanzable de cada bolsa y con que valor se consigue.
    columnas: list[tuple[Any, np.ndarray, np.ndarray]] = []
    for knob in knobs:
        valores = candidatos_de_knob(knob, puntos=puntos, catalogo=catalogo)
        if valores is None:
            continue
        us = []
        for valor in valores:
            overrides = [{"variable": f, "valor": valor} for f in knob.feature_names]
            X_sim, aplicadas, _avisos = aplicar_overrides_instancias(
                X_base, feature_names, overrides,
                label_encoders=label_encoders, max_values_imputed=max_values_imputed,
            )
            if not aplicadas:
                us = []
                break
            us.append(np.asarray(
                predictor.predict(X_sim, instance_bag=instance_bag), dtype=float))
        if not us:
            continue
        matriz = np.vstack(us)                       # (candidatos, n_bolsas)
        indice_mejor = matriz.argmin(axis=0)
        columnas.append((knob, matriz.min(axis=0),
                         [valores[i] for i in indice_mejor]))

    def _log10(valor: float) -> float:
        # Piso comun para los dos lados de la resta: sin el, un u-hat de cero -- que el
        # modelo puede devolver -- daria -inf y la caida seria infinita para cualquier
        # variable que lo alcance.
        return float(np.log10(max(float(valor), 1e-12)))

    resultado: dict[str, dict[str, Any]] = {}
    for b, fid in enumerate(fids):
        if fid in resultado:
            continue
        objetivo = umbral_u_para_clase_minima(float(n_obs[b]), predictor.geometria)
        # `alcanza` promete un CAMBIO de grupo, asi que un vano que ya esta en el mas
        # bajo no lo cumple con nada: lo cumpliria con todo. Medido, uno con u=0,415 y
        # meta 4,24 daba sus diez variables en verde, senialando como palancas decisivas
        # a diez que no mueven nada.
        ya_en_minima = bool(clase_base[b] == 0)
        base_log = _log10(u_base[b])
        brecha = None if objetivo is None else base_log - _log10(objetivo)
        filas = []
        for knob, mejor_u, mejor_valor in columnas:
            # El optimo nunca puede quedar por ENCIMA de la base: el valor observado
            # esta dentro del rango, asi que en el peor caso la rejilla lo empata.
            u_optimo = float(min(mejor_u[b], u_base[b]))
            caida = base_log - _log10(u_optimo)
            filas.append({
                "knob_id": knob.id,
                "label": knob.label,
                "grupo": (grupos or {}).get(knob.id, ""),
                "valor": mejor_valor[b],
                "u_optimo": u_optimo,
                "caida_log": caida,
                # Que fraccion del camino al grupo mas bajo cubre esta sola variable.
                # None cuando el vano ya esta en el grupo mas bajo (no hay camino) o
                # cuando ese grupo es inalcanzable con sus eventos.
                "avance": (None if not brecha or brecha <= 0
                           else float(min(caida / brecha, 1.0))),
                "alcanza": (not ya_en_minima and objetivo is not None
                            and u_optimo <= objetivo),
            })
        filas.sort(key=lambda fila: fila["caida_log"], reverse=True)
        filas = _top_con_cuota(filas, top=int(top), grupos=grupos)
        resultado[fid] = {
            "u_base": float(u_base[b]),
            "n_obs": int(n_obs[b]),
            "clase_base": int(clase_base[b]),
            "ya_en_clase_minima": ya_en_minima,
            "objetivo_u": objetivo,
            "alcanza_alguna": any(fila["alcanza"] for fila in filas),
            "filas": filas,
        }
    return resultado


# --- Al reentrenar el MIL, o al cambiar las variables a simular ------------------------
#
# Todo lo que hay debajo esta calibrado contra ESTE artefacto y ESTE
# `data/Variables_simular.xlsx`. Los numeros que sostienen sus decisiones -- cuantos
# pasos, cuantos puntos de rejilla, si vale la pena buscar mejor -- se midieron, y no
# sobreviven a un reentrenamiento ni a un ajuste de rangos. Hay que rehacerlos, y el
# procedimiento esta en `docs/mil-vano-ventana-estado-y-mejoras.md`.
#
# Lo que se rompe EN SILENCIO, sin lanzar ningun error:
#
# 1. Los candidatos salen del `.xlsx` via `candidatos_del_panel`. Una variable nueva, un
#    `Tipo` distinto o un rango movido cambian el diagnostico con ellos. Si el archivo
#    ofrece una categoria que el codificador no conoce, la simulacion falla a mitad;
#    `incoherencias_del_catalogo` lo reporta.
# 2. El vocabulario de `Tipo` es un contrato: `categorical | numeric | int`, mas el
#    nombre anterior `numeric-entero`. Un tipo nuevo cae al deslizador continuo sin
#    avisar, que es como se colo el defecto al renombrarse la columna.
# 3. La meta la fija `n_obs`, que NUNCA se simula. El umbral del grupo Bajo se desploma
#    con los eventos -- 4,41 con uno, 0,0029 con cuarenta y seis --, asi que otra
#    geometria mueve todas las metas a la vez. Eso decide cuantos vanos son alcanzables
#    mucho mas que la calidad del buscador: medido sobre DON23L14 V9, bajar al grupo
#    Bajo exige 1,37 decadas y las palancas de intervencion dan 0,06.
#
MAX_FILAS_POR_PASADA = 50_000
"""Cuantas filas como mucho arma `plan_hacia_clase_minima` en una sola pasada al modelo.

Los ensayos de una ronda se apilan para puntuarlos juntos, y con una seleccion grande esa
matriz crece con el numero de candidatos por el de instancias. El troceo no cambia el
resultado -- cada ensayo vive en sus propias bolsas -- y evita pedir varios GB de golpe.

Era 400.000. MEDIDO sobre una ventana real de 676 instancias y 162 ensayos:

    400.000   11,3 s   pico +1.102 MB
    100.000   11,1 s   pico    +26 MB
     50.000   11,1 s   pico     +0 MB
     10.000   11,4 s   pico     +0 MB

El plan sale IDENTICO en los cuatro -- mismos pasos, mismo orden, misma clase final --,
asi que 1,1 GB de pico no compraban nada. Y no es un intercambio: trocear mas fino sale
igual o algo mas rapido, porque un tensor de 50.000 filas cabe en cache y uno de 400.000
no. `test_el_troceo_no_cambia_el_plan_solo_el_pico_de_memoria` fija la invariante.
"""


def _clave_valor(valor: Any) -> Any:
    """Clave hashable para memorizar la expansion de un candidato.

    Los valores numericos llegan como `np.float64` y los categoricos como texto. `float`
    y `np.float64` son iguales y comparten hash, asi que basta con normalizar a tipos de
    Python para que dos rutas distintas al mismo valor compartan entrada.
    """
    if isinstance(valor, (np.floating, np.integer)):
        return valor.item()
    return valor


def plan_hacia_clase_minima(
    predictor: Any,
    X_inst: np.ndarray,
    *,
    seleccion: Mapping[str, Any],
    feature_names: Sequence[str],
    knobs: Sequence[Any],
    puntos: int = 9,
    max_pasos: int = 4,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
    catalogo: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """La COMBINACION de cambios que lleva a cada vano al grupo mas bajo, o lo mas cerca
    que se pueda.

    El ranking de una variable a la vez alcanza en Medio y casi nunca mas arriba. Medido
    sobre 59 bolsas de 40 circuitos: en Medio, 20 de 33 llegan con una sola variable; en
    Medio-Alto, 0 de 18; en Alto, 0 de 8, y la mejor variable cubre apenas el 60% y el
    49% del camino. No es la rareza de un vano: es el caso normal justo en los grupos
    donde la pregunta importa, y por eso esto no es un extra del ranking sino su
    continuacion.

    Es un descenso por coordenadas, GOLOSO: en cada ronda se prueban todos los
    candidatos de todos los controles que ese vano no haya usado todavia, se aplica el
    que mas baja su u-hat, y se repite hasta caer en el grupo mas bajo, agotar
    `max_pasos` o dejar de mejorar. Goloso y no exhaustivo por una razon de tamanio: con
    18 controles y 9 valores, dos cambios simultaneos ya son 13 mil combinaciones, y
    cuatro son 26 millones -- fuera del presupuesto de un boton que debe sentirse
    inmediato. El precio se paga y se dice: el plan es bueno, no demostrablemente el
    minimo.

    Cada control entra COMO MUCHO UNA VEZ por vano. Un plan que reajusta dos veces la
    misma variable no es una orden de trabajo mas barata, es la misma obra contada dos
    veces.

    Las rondas se comparten entre todos los vanos: un candidato se aplica a la vez sobre
    el estado propio de cada bolsa y la pasada devuelve un u-hat por bolsa, asi que cada
    una elige su mejor paso sin que la ronda cueste una tanda por vano. Cuesta
    `1 + rondas * candidatos` pasadas, y se corta en cuanto no queda ningun vano por
    resolver.

    Se para al ALCANZAR: un plan de mantenimiento no agrega obra despues del objetivo,
    porque cada paso de mas es dinero que no compra nada. Y cuando ni moviendolo todo se
    llega, se devuelve lo conseguido con `alcanza=False`, que vale mas que un plan que
    insinua lo contrario.
    """
    if int(seleccion["n_bolsas"]) == 0:
        return {}

    filas_idx = np.asarray(seleccion["filas"], dtype=np.int64)
    instance_bag = np.asarray(seleccion["instance_bag"], dtype=np.int64)
    n_obs = np.asarray(seleccion["n_obs"], dtype=float)
    fids = [str(f) for f in seleccion["fid"]]
    X_base = np.asarray(X_inst[filas_idx], dtype=np.float64)
    n_bolsas = len(fids)

    candidatos = [(knob, valores) for knob in knobs
                  if (valores := candidatos_de_knob(
                      knob, puntos=puntos, catalogo=catalogo)) is not None]
    objetivos = [umbral_u_para_clase_minima(float(n), predictor.geometria) for n in n_obs]

    # La expansion de un control a las columnas que toca NO depende del vano ni de la
    # ronda, asi que se hace una sola vez. Antes se rehacia dentro del doble bucle: por
    # cada par (control, valor) se volvia a expandir el estado ENTERO de las diez bolsas.
    # Medido sobre una seleccion de 10 bolsas y 18 instancias, el 67% de los 2,75 s de
    # esta funcion se iba ahi, en Python, sin tocar el modelo.
    expansion = {(knob.id, _clave_valor(valor)): expand_knob_overrides({knob.id: valor}, knobs)
                 for knob, valores in candidatos for valor in valores}

    def _matriz_con(estado_por_bolsa: list[dict[str, Any]]) -> np.ndarray:
        """La matriz de instancias con los cambios ya fijados de cada bolsa."""
        overrides = {
            fids[b]: [o for knob_id, valor in estado.items()
                      for o in expansion[(knob_id, _clave_valor(valor))]]
            for b, estado in enumerate(estado_por_bolsa) if estado
        }
        if not overrides:
            return X_base
        X, _aplicadas, _avisos = aplicar_overrides_por_vano(
            X_base, feature_names, overrides, instance_bag=instance_bag,
            fids=fids, label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
        )
        return X

    def _u_de(X: np.ndarray, bolsas: np.ndarray) -> np.ndarray:
        return np.asarray(predictor.predict(X, instance_bag=bolsas), dtype=float)

    def _u_con(estado_por_bolsa: list[dict[str, Any]]) -> np.ndarray:
        """u-hat de cada bolsa con SU propio conjunto de cambios ya fijados."""
        return _u_de(_matriz_con(estado_por_bolsa), instance_bag)

    def _u_de_los_ensayos(X_estado: np.ndarray, ensayos: list) -> np.ndarray:
        """Un u-hat por (ensayo, bolsa), evaluando TODOS los ensayos de la ronda juntos.

        Cada ensayo es el estado vigente mas UN cambio, asi que su matriz sale de aplicar
        ese cambio sobre `X_estado` en vez de rearmar el estado desde cero. Las matrices
        se apilan con el `instance_bag` desplazado -- el ensayo `t` usa las bolsas
        `t * n_bolsas + b` -- y el modelo las puntua en una sola pasada.

        Es la misma cuenta que hacia el bucle -- mismo estado base, mismos candidatos,
        mismas filas -- pero NO da el mismo numero bit a bit, y conviene saber por que:
        la suma en punto flotante no es asociativa, asi que puntuar una matriz apilada
        cambia el orden de reduccion interno del modelo respecto de puntuar 18 filas.

        Lo que importa es si ese ruido llega a cambiar una DECISION, porque el descenso
        es goloso y dos candidatos casi empatados podrian invertirse. Medido contra la
        implementacion anterior sobre 25 vanos de 3 circuitos: los 25 conservan los
        MISMOS pasos, en el mismo orden y con los mismos valores, y la misma clase final.
        La peor diferencia relativa en `u_final` es 2,9e-05, del orden del float32 en que
        vive el modelo. El plan que alguien ejecuta en campo no cambia; el u-hat que se
        muestra puede variar en el quinto decimal.

        Se trocea por `MAX_FILAS_POR_PASADA` para que una seleccion grande no arme una
        matriz de varios GB: el troceo no cambia el resultado porque cada ensayo vive en
        sus propias bolsas.
        """
        por_ensayo = np.empty((len(ensayos), n_bolsas), dtype=float)
        bloque: list[np.ndarray] = []
        bolsas: list[np.ndarray] = []
        indices: list[int] = []
        filas_en_bloque = 0

        def _vaciar():
            if not bloque:
                return
            u = _u_de(np.concatenate(bloque), np.concatenate(bolsas))
            for k, t in enumerate(indices):
                por_ensayo[t] = u[k * n_bolsas:(k + 1) * n_bolsas]
            bloque.clear(); bolsas.clear(); indices.clear()

        for t, (knob, valor, elegibles) in enumerate(ensayos):
            overrides = {fids[b]: expansion[(knob.id, _clave_valor(valor))]
                         for b in elegibles}
            X_t, _a, _av = aplicar_overrides_por_vano(
                X_estado, feature_names, overrides, instance_bag=instance_bag,
                fids=fids, label_encoders=label_encoders,
                max_values_imputed=max_values_imputed,
            )
            if filas_en_bloque and filas_en_bloque + len(X_t) > MAX_FILAS_POR_PASADA:
                _vaciar()
                filas_en_bloque = 0
            bloque.append(X_t)
            bolsas.append(instance_bag + len(indices) * n_bolsas)
            indices.append(t)
            filas_en_bloque += len(X_t)
        _vaciar()
        return por_ensayo

    estado: list[dict[str, Any]] = [{} for _ in range(n_bolsas)]
    u_actual = _u_con(estado)
    u_base = u_actual.copy()
    clase, _ = asignar_clase(n_obs, u_actual, predictor.geometria)
    clase_base = np.asarray(clase, dtype=int)

    # La ESCALERA de objetivos. Se apunta a Bajo; cuando Bajo no existe para esa
    # cantidad de eventos -- y con eventos suficientes deja de existir: el umbral cae de
    # 4,41 con un evento a 0,0029 con cuarenta y seis -- se apunta al grupo de abajo del
    # suyo. Antes, un vano en ese caso se quedaba sin meta y gastaba las cuatro rondas
    # persiguiendo algo imposible; ahora para en cuanto consigue bajar un grupo, que es
    # una mejora real y es donde termina la orden de trabajo.
    objetivo_clase: list[int] = []
    objetivo_efectivo: list[float | None] = []
    for b in range(n_bolsas):
        if objetivos[b] is not None:
            objetivo_clase.append(0)
            objetivo_efectivo.append(objetivos[b])
            continue
        siguiente = max(int(clase_base[b]) - 1, 0)
        objetivo_clase.append(siguiente)
        objetivo_efectivo.append(
            umbral_u_para_clase(float(n_obs[b]), predictor.geometria, siguiente)
        )

    pendientes = [b for b in range(n_bolsas) if int(clase_base[b]) != objetivo_clase[b]]
    pasos: list[list[dict[str, Any]]] = [[] for _ in range(n_bolsas)]

    for _ronda in range(int(max_pasos)):
        if not pendientes:
            break
        mejor = {b: (u_actual[b], None, None) for b in pendientes}
        # El estado de la ronda es FIJO, asi que su matriz se arma UNA vez y cada ensayo
        # solo le agrega su propio cambio encima.
        X_estado = _matriz_con(estado)
        ensayos = [(knob, valor, elegibles)
                   for knob, valores in candidatos
                   for valor in valores
                   if (elegibles := [b for b in pendientes if knob.id not in estado[b]])]
        if not ensayos:
            break
        u_ensayos = _u_de_los_ensayos(X_estado, ensayos)
        for t, (knob, valor, elegibles) in enumerate(ensayos):
            for b in elegibles:
                if u_ensayos[t, b] < mejor[b][0]:
                    mejor[b] = (float(u_ensayos[t, b]), knob, valor)
        siguen = []
        for b in pendientes:
            u_mejor, knob, valor = mejor[b]
            if knob is None:            # ningun candidato mejora: este vano no avanza mas
                continue
            estado[b][knob.id] = valor
            pasos[b].append({"knob_id": knob.id, "label": knob.label, "valor": valor,
                             "u_despues": u_mejor})
            u_actual[b] = u_mejor
            objetivo = objetivo_efectivo[b]
            if objetivo is None or u_mejor > objetivo:
                siguen.append(b)
        pendientes = siguen

    clase_final, _ = asignar_clase(n_obs, u_actual, predictor.geometria)
    clase_final = np.asarray(clase_final, dtype=int)
    resultado: dict[str, dict[str, Any]] = {}
    for b, fid in enumerate(fids):
        if fid in resultado:
            continue
        baja = bool(clase_final[b] < clase_base[b])
        propios = pasos[b]
        if baja and propios:
            # Se recorta al PRIMER paso que ya consigue el grupo final. Lo que viene
            # despues es obra que no compro ningun cambio de grupo, y una orden de
            # trabajo no se cotiza por lo que no cambia nada. Medido sobre DON23L14 V11:
            # 8 vanos bajaban de grupo y seguian acumulando pasos detras de un Bajo que
            # no alcanzaban -- 18 pasos de mas.
            #
            # Solo cuando BAJA. Un plan que no cambia el grupo conserva sus pasos
            # enteros: esos si bajan el UITI, y recortarlos diria "no hay nada que hacer
            # aqui", que es otra cosa.
            clases_paso, _ = asignar_clase(
                np.full(len(propios), float(n_obs[b])),
                np.array([float(p["u_despues"]) for p in propios]),
                predictor.geometria,
            )
            clases_paso = np.asarray(clases_paso, dtype=int)
            llegan = np.flatnonzero(clases_paso <= int(clase_final[b]))
            if llegan.size:
                propios = propios[: int(llegan[0]) + 1]
        resultado[fid] = {
            "u_base": float(u_base[b]),
            "u_final": float(u_actual[b]),
            "clase_base": int(clase_base[b]),
            "clase_final": int(clase_final[b]),
            "objetivo_u": objetivos[b],
            # A que grupo se apunto de verdad: 0 cuando Bajo existe para esos eventos,
            # y el de abajo del suyo cuando no. Sin esto, `alcanza: False` no distingue
            # "no llegamos" de "Bajo no era alcanzable ni en teoria".
            "objetivo_clase": int(objetivo_clase[b]),
            "alcanza": bool(clase_final[b] == 0),
            # La pregunta operativa no es solo si llega a Bajo: bajar de Alto a
            # Medio-Alto es una mejora, y sin este campo se lee igual que no moverse.
            "baja_de_grupo": baja,
            "pasos": propios,
        }
    return resultado
