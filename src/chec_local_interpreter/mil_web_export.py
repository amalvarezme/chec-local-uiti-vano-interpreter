"""Export the MIL bag model's INFERENCE path so a browser can run it.

Notebook 06's "Simular" button runs `MILBagRegressor` in the kernel. Its 22
numeric knobs are continuous and combinable, so there is no finite set of
results to precompute: to make the button work in the exported HTML panel the
forward pass itself has to travel. This module is what makes that possible and
checkable:

- `extraer_pesos_mil` pulls out ONLY the tensors `p_bag` actually depends on
  under `fusion='film'`. Measured on `mil_vano_ventana_v1.pt`, that is 89.658
  of the model's 150.926 parameters -- the decoders, the per-modality
  classifiers, regressors and reliability heads are dead paths for the
  prediction and would be 61.268 parameters of payload saying nothing.
- `predecir_numpy` is the same forward in pure numpy, with NO torch. It is the
  reference the panel's JavaScript is transcribed from, one function at a time,
  and `tests/test_mil_web_export.py` pins it against the real torch module. A
  hand-written JS forward that nothing checks would be a silent-wrong-answer
  machine; this is what keeps it honest.
- `rango_efectivo` closes the last gap. The graph panel voids itself when the
  gate matrix collapses, and that verdict needs the participation ratio of the
  centred matrix's singular values. No SVD is needed for it: with `C` the
  centred matrix, `sum(sv^2) == ||C||_F^2` and `sum(sv^4) == ||C^T C||_F^2`, so
  the ratio comes straight from two Frobenius norms -- exact, and a few lines
  in any language.

Encoders are exported as an ORDERED LIST OF OPS (`linear`, `relu`,
`layernorm`, `dropout`) read straight off the `nn.Sequential`, not as a
hardcoded stack. The consumer becomes a tiny interpreter, and adding a layer in
`_ModalityEncoder` travels on its own instead of silently changing what the
browser computes.
"""

from __future__ import annotations

import base64
from typing import Any, Mapping, Sequence

import numpy as np

# Dropout is the identity at eval; it is exported anyway so the op list stays a
# faithful description of the module rather than a filtered one.
_TIPOS_SOPORTADOS = ("linear", "relu", "layernorm", "dropout")


def _arreglo(tensor: Any) -> np.ndarray:
    return np.asarray(tensor.detach().cpu().numpy(), dtype=np.float32)


def _lineal(modulo: Any) -> dict[str, Any]:
    # Torch stores Linear as (salida, entrada) and computes `x @ W.T + b`. The
    # transpose is done HERE, once, so every consumer can do a plain `x @ W`.
    return {"tipo": "linear", "W": _arreglo(modulo.weight).T.copy(), "b": _arreglo(modulo.bias)}


def _layernorm(modulo: Any) -> dict[str, Any]:
    return {"tipo": "layernorm", "w": _arreglo(modulo.weight),
            "b": _arreglo(modulo.bias), "eps": float(modulo.eps)}


def _capas_de_secuencial(secuencial: Any) -> list[dict[str, Any]]:
    """Read an `nn.Sequential` into an ordered op list, refusing anything this
    module has not been taught to reproduce -- an unknown layer must fail here,
    where the message says so, and never be skipped into a browser that would
    then compute a different function."""
    capas: list[dict[str, Any]] = []
    for modulo in secuencial:
        nombre = type(modulo).__name__
        if nombre == "Linear":
            capas.append(_lineal(modulo))
        elif nombre == "ReLU":
            capas.append({"tipo": "relu"})
        elif nombre == "LayerNorm":
            capas.append(_layernorm(modulo))
        elif nombre == "Dropout":
            capas.append({"tipo": "dropout"})
        else:
            raise ValueError(
                f"Capa no soportada por el exportador web: {nombre}. El panel del "
                "navegador reproduce el forward capa por capa; agregar uno nuevo aca "
                "es lo que impide que el navegador calcule otra cosa en silencio."
            )
    return capas


def extraer_pesos_mil(predictor: Any) -> dict[str, Any]:
    """Every tensor `p_bag` depends on, as numpy arrays.

    Only `fusion='film'` is supported, which is what `mil_vano_ventana_v1.pt`
    is. The other two fusions read different heads, and exporting one while
    computing the other is precisely the failure this refuses to allow.
    """
    modelo = predictor.model
    if getattr(modelo, "fusion", None) != "film":
        raise ValueError(
            f"El exportador web solo cubre fusion='film'; el modelo trae "
            f"{getattr(modelo, 'fusion', None)!r}. Las otras fusiones leen otras cabezas."
        )
    base = modelo.base

    modalidades = []
    for nombre, indices in base.modality_feature_indices.items():
        codificador = base.modality_encoders[list(base.modality_feature_indices).index(nombre)]
        atencion = codificador.feature_attention
        modalidades.append({
            "nombre": str(nombre),
            "indices": np.asarray(list(indices), dtype=np.int32),
            "atencion": {
                "norma": _layernorm(atencion.normalization),
                "scorer": _lineal(atencion.scorer),
                "escala": float(atencion.scale),
            },
            "red": _capas_de_secuencial(codificador.network),
        })

    geometria = predictor.geometria
    return {
        "modalidades": modalidades,
        "pool": {"proyeccion": _lineal(modelo.attention_pool.score_projection),
                 "cabeza": _lineal(modelo.attention_pool.score_head)},
        "compuertas": _lineal(modelo.gate_decoder.linear),
        "alpha": float(modelo.alpha),
        "aristaFilas": np.asarray(modelo.edge_rows.cpu().numpy(), dtype=np.int32),
        "aristaColumnas": np.asarray(modelo.edge_cols.cpu().numpy(), dtype=np.int32),
        "aristaValores": _arreglo(modelo.edge_values),
        "film": {
            "indiceModulada": int(modelo.film_modulated_index),
            "gamma": _lineal(modelo.film_gamma),
            "beta": _lineal(modelo.film_beta),
            "cabeza": _lineal(modelo.film_head),
        },
        "embedDim": int(base.embed_dim),
        "nModalidades": int(base.n_modalities),
        "nFeatures": int(base.input_dim),
        "geometria": {
            "offset": np.asarray(geometria.offset, dtype=np.float64),
            "scale": np.asarray(geometria.scale, dtype=np.float64),
            "logs": [bool(v) for v in geometria.logs],
            "centroides": np.asarray(geometria.centroides, dtype=np.float64),
        },
    }


# --- Forward de referencia, sin torch ------------------------------------------------


def _aplicar_capas(x: np.ndarray, capas: Sequence[Mapping[str, Any]]) -> np.ndarray:
    for capa in capas:
        tipo = capa["tipo"]
        if tipo == "linear":
            x = x @ capa["W"] + capa["b"]
        elif tipo == "relu":
            x = np.maximum(x, 0.0)
        elif tipo == "layernorm":
            media = x.mean(axis=-1, keepdims=True)
            var = x.var(axis=-1, keepdims=True)
            x = (x - media) / np.sqrt(var + capa["eps"]) * capa["w"] + capa["b"]
        elif tipo == "dropout":
            pass  # identidad en eval
        else:  # pragma: no cover - `_capas_de_secuencial` ya lo impide
            raise ValueError(tipo)
    return x


def _softmax_filas(x: np.ndarray) -> np.ndarray:
    desplazado = x - x.max(axis=-1, keepdims=True)
    exp = np.exp(desplazado)
    return exp / exp.sum(axis=-1, keepdims=True)


def _codificar(pesos: Mapping[str, Any], x: np.ndarray) -> list[np.ndarray]:
    salidas = []
    for modalidad in pesos["modalidades"]:
        entrada = x[:, modalidad["indices"]]
        atencion = modalidad["atencion"]
        normalizado = _aplicar_capas(entrada, [atencion["norma"]])
        puntajes = normalizado @ atencion["scorer"]["W"] + atencion["scorer"]["b"]
        entrada = entrada * _softmax_filas(puntajes) * atencion["escala"]
        salidas.append(_aplicar_capas(entrada, modalidad["red"]))
    return salidas


def _agrupar(pesos: Mapping[str, Any], z: np.ndarray, instance_bag: np.ndarray,
             n_bags: int) -> np.ndarray:
    """Segment attention pooling. The per-bag max subtraction is the same
    numerical-stability shim torch does and does not change the result."""
    pool = pesos["pool"]
    puntajes = (np.tanh(z @ pool["proyeccion"]["W"] + pool["proyeccion"]["b"])
                @ pool["cabeza"]["W"] + pool["cabeza"]["b"]).reshape(-1)
    maximos = np.full(n_bags, -np.inf, dtype=np.float64)
    np.maximum.at(maximos, instance_bag, puntajes)
    exp = np.exp(puntajes - maximos[instance_bag])
    suma = np.zeros(n_bags, dtype=np.float64)
    np.add.at(suma, instance_bag, exp)
    atencion = exp / np.maximum(suma[instance_bag], 1e-12)
    z_bolsa = np.zeros((n_bags, z.shape[1]), dtype=np.float64)
    np.add.at(z_bolsa, instance_bag, atencion[:, None] * z)
    return z_bolsa


def predecir_numpy(
    pesos: Mapping[str, Any],
    X: np.ndarray,
    instance_bag: np.ndarray,
    n_bags: int,
) -> dict[str, np.ndarray]:
    """`u_hat` per bag plus the edge gates, without torch.

    Mirrors `MILBagRegressor.forward` + `BagPredictor.predict`: encode (gate
    source), pool, decode one gate per bag, propagate edge-wise onto every
    instance of that bag, re-encode through the SAME weights, re-pool, FiLM,
    head, and finally `expm1`.
    """
    X = np.asarray(X, dtype=np.float32)
    instance_bag = np.asarray(instance_bag, dtype=np.int64)
    if X.shape[0] == 0:
        return {"u": np.zeros(0), "compuertas": np.zeros((0, len(pesos["aristaValores"])))}

    z1 = np.concatenate(_codificar(pesos, X), axis=1)
    z_bolsa = _agrupar(pesos, z1, instance_bag, n_bags)
    compuertas = 2.0 / (1.0 + np.exp(
        -(z_bolsa @ pesos["compuertas"]["W"] + pesos["compuertas"]["b"])))

    # Propagacion: `x' = x + alpha * gate * peso * x[:, fila]`, acumulado en la
    # COLUMNA de cada arista. Toda columna que no aparezca en `aristaColumnas`
    # queda intacta, exactamente como el `index_add(1, ...)` de torch.
    filas, columnas = pesos["aristaFilas"], pesos["aristaColumnas"]
    mensajes = (pesos["alpha"] * compuertas[instance_bag]
                * pesos["aristaValores"][None, :] * X[:, filas])
    propagado = np.array(X, dtype=np.float64, copy=True)
    np.add.at(propagado, (slice(None), columnas), mensajes)

    z2 = np.concatenate(_codificar(pesos, propagado.astype(np.float32)), axis=1)
    z_bolsa_2 = _agrupar(pesos, z2, instance_bag, n_bags)

    embed = pesos["embedDim"]
    rebanadas = [z_bolsa_2[:, i * embed:(i + 1) * embed] for i in range(pesos["nModalidades"])]
    indice = pesos["film"]["indiceModulada"]
    modulada = rebanadas[indice]
    contexto = np.concatenate([r for i, r in enumerate(rebanadas) if i != indice], axis=1)
    gamma = contexto @ pesos["film"]["gamma"]["W"] + pesos["film"]["gamma"]["b"]
    beta = contexto @ pesos["film"]["beta"]["W"] + pesos["film"]["beta"]["b"]
    z_film = modulada * (1.0 + gamma) + beta
    p_bag = (z_film @ pesos["film"]["cabeza"]["W"] + pesos["film"]["cabeza"]["b"]).reshape(-1)
    return {"u": np.expm1(p_bag), "compuertas": compuertas}


def clase_numpy(n_obs: np.ndarray, u: np.ndarray, geometria: Mapping[str, Any],
                *, eps: float = 1e-6) -> np.ndarray:
    """Nearest-centroid class, mirroring `criticality_assignment.asignar_clase`."""
    n_obs = np.asarray(n_obs, dtype=np.float64)
    u = np.asarray(u, dtype=np.float64)
    log_x, log_y = geometria["logs"]
    x0 = np.log10(np.maximum(n_obs, eps)) if log_x else n_obs
    x1 = np.log10(np.maximum(u, eps)) if log_y else u
    offset, escala = geometria["offset"], geometria["scale"]
    z = np.stack([(x0 - offset[0]) / escala[0], (x1 - offset[1]) / escala[1]], axis=-1)
    centroides = np.asarray(geometria["centroides"], dtype=np.float64)
    return np.argmin(((z[:, None, :] - centroides[None, :, :]) ** 2).sum(axis=-1), axis=-1)


def rango_efectivo(gate_means: np.ndarray) -> float:
    """`estadistico_colapso`'s effective rank WITHOUT an SVD.

    It is the participation ratio of the centred matrix's singular values,
    `(sum sv^2)^2 / sum sv^4`. Both sums are Frobenius norms of matrices that
    are cheap to form: `sum sv^2 == ||C||_F^2` and `sum sv^4 == ||C^T C||_F^2`,
    because the `sv^2` are the eigenvalues of `C^T C`. Exact, and it means the
    browser needs no eigensolver to decide whether to void the graph panel.
    """
    C = np.asarray(gate_means, dtype=np.float64)
    if C.ndim != 2 or C.shape[0] == 0:
        return 0.0
    C = C - C.mean(axis=0, keepdims=True)
    energia = float((C * C).sum())
    if energia <= 0:
        return 0.0
    gram = C.T @ C
    return float(energia ** 2 / (gram * gram).sum())


def a_base64(arreglo: np.ndarray, dtype: str = "float32") -> str:
    """Bytes of an array as base64. Weights and instance matrices travel this
    way and not as JSON numbers: a float32 costs 4 bytes here against ~12
    characters as text, and the browser rebuilds it with one `Float32Array`."""
    return base64.b64encode(np.ascontiguousarray(arreglo, dtype=dtype).tobytes()).decode("ascii")


def pesos_a_json(pesos: Mapping[str, Any]) -> dict[str, Any]:
    """The weight dict with every array turned into `{b64, forma}`, ready for
    `json.dumps`."""
    def convertir(valor: Any) -> Any:
        if isinstance(valor, np.ndarray):
            tipo = "int32" if np.issubdtype(valor.dtype, np.integer) else "float32"
            return {"b64": a_base64(valor, tipo), "forma": list(valor.shape), "tipo": tipo}
        if isinstance(valor, Mapping):
            return {k: convertir(v) for k, v in valor.items()}
        if isinstance(valor, (list, tuple)):
            return [convertir(v) for v in valor]
        return valor

    return convertir(dict(pesos))
