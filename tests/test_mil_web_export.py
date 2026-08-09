"""The browser's copy of the MIL forward has to compute what torch computes.

`mil_web_export.predecir_numpy` is the reference notebook 06's panel JavaScript
is transcribed from, one function at a time. If it drifts from
`MILBagRegressor`, the exported HTML's "Simular" button answers confidently
with the wrong criticality and nothing on screen says so -- which is worse than
not shipping the button. These tests are what stands between those two.

They build a REAL `MILBagRegressor` with random weights instead of loading
`data/models/mil_vano_ventana_v1.pt`: that artifact is gitignored (it is
produced by notebook 05), so a test bound to it would not run on a fresh
checkout. Random weights exercise exactly the same code path, and a mismatch in
any layer shows up the same way.
"""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from chec_impacto.interpretability.mgcecdl_graph import estadistico_colapso
from chec_impacto.models.mgcecdl import MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import GraphEdgeIndex
from chec_impacto.models.mgcecdl_mil import MILBagRegressor
from chec_local_interpreter.mil_web_export import (
    clase_numpy,
    extraer_pesos_mil,
    pesos_a_json,
    predecir_numpy,
    rango_efectivo,
)

N_FEATURES = 12
EMBED_DIM = 8
HIDDEN_DIM = 16


class _PredictorFalso:
    """Only what `extraer_pesos_mil` reads: the module and the geometry."""

    def __init__(self, model, geometria):
        self.model = model
        self.geometria = geometria


class _Geometria:
    def __init__(self):
        self.offset = np.array([0.1, 0.2])
        self.scale = np.array([1.3, 0.7])
        self.logs = (False, True)
        self.centroides = np.array([[-1.0, -1.0], [0.0, 0.5], [1.0, 0.0], [2.0, 1.5]])


def _modelo(semilla: int = 0):
    torch.manual_seed(semilla)
    indices = {"climaticos": list(range(0, 7)), "estructurales": list(range(7, N_FEATURES))}
    base = MGCECDLRegressor(
        modality_feature_indices=indices, hidden_dim=HIDDEN_DIM, embed_dim=EMBED_DIM,
        dropout=0.1,
    )
    generador = np.random.default_rng(semilla)
    adjacency = np.zeros((N_FEATURES, N_FEATURES), dtype=np.float32)
    pares = [(0, 8), (1, 2), (3, 9), (7, 4), (5, 11), (10, 6)]
    for fila, columna in pares:
        adjacency[fila, columna] = float(generador.uniform(0.2, 1.0))
    edge_index = GraphEdgeIndex(
        pairs=np.array(pares, dtype=np.int64),
        names=tuple((f"f{f}", f"f{c}") for f, c in pares),
        weights=np.array([adjacency[f, c] for f, c in pares], dtype=np.float32),
    )
    modelo = MILBagRegressor(
        base=base, adjacency=adjacency, edge_index=edge_index, alpha=0.3,
        fusion="film", film_modulated_modality="estructurales",
    )
    # Pesos no triviales: FiLM arranca en cero (identidad) a proposito, asi que
    # dejarlo asi no probaria ninguna de sus dos capas.
    with torch.no_grad():
        for parametro in modelo.parameters():
            parametro.add_(torch.randn_like(parametro) * 0.15)
    modelo.eval()
    return modelo


def _bolsas(n_inst: int, n_bags: int, semilla: int = 3):
    generador = np.random.default_rng(semilla)
    # Cada bolsa con al menos una instancia, y tamanios desparejos: el pooling es
    # invariante a cardinalidad y con bolsas iguales ese error no aparece.
    instance_bag = np.concatenate([
        np.arange(n_bags), generador.integers(0, n_bags, size=n_inst - n_bags)
    ]).astype(np.int64)
    instance_bag.sort()
    X = generador.normal(size=(n_inst, N_FEATURES)).astype(np.float32) * 3.0
    return X, instance_bag


def _u_torch(modelo, X, instance_bag, n_bags):
    with torch.no_grad():
        salida = modelo(torch.as_tensor(X, dtype=torch.float32),
                        torch.as_tensor(instance_bag, dtype=torch.long), n_bags)
    return np.expm1(salida["p_bag"].numpy()), salida["edge_gates"].numpy()


def test_predecir_numpy_matches_the_torch_module():
    """La prueba que sostiene todo el boton: mismo u-hat que el modulo real."""
    modelo = _modelo()
    pesos = extraer_pesos_mil(_PredictorFalso(modelo, _Geometria()))
    X, instance_bag = _bolsas(n_inst=57, n_bags=9)
    n_bags = 9

    u_esperado, _ = _u_torch(modelo, X, instance_bag, n_bags)
    resultado = predecir_numpy(pesos, X, instance_bag, n_bags)

    assert resultado["u"].shape == (n_bags,)
    np.testing.assert_allclose(resultado["u"], u_esperado, rtol=1e-4, atol=1e-5)


def test_predecir_numpy_matches_the_edge_gates_too():
    """El grafo del panel se dibuja con estas compuertas: si se desvian, el
    navegador muestra una estructura que el modelo no produjo."""
    modelo = _modelo(semilla=1)
    pesos = extraer_pesos_mil(_PredictorFalso(modelo, _Geometria()))
    X, instance_bag = _bolsas(n_inst=40, n_bags=6, semilla=5)

    _, compuertas_esperadas = _u_torch(modelo, X, instance_bag, 6)
    resultado = predecir_numpy(pesos, X, instance_bag, 6)

    np.testing.assert_allclose(resultado["compuertas"], compuertas_esperadas,
                               rtol=1e-4, atol=1e-5)


def test_predecir_numpy_survives_a_single_instance_bag():
    """Una bolsa de una sola instancia es el caso comun (mediana medida: 1
    evento por celda vano x ventana) y es donde un softmax por segmento mal
    hecho divide por cero."""
    modelo = _modelo(semilla=2)
    pesos = extraer_pesos_mil(_PredictorFalso(modelo, _Geometria()))
    X = np.random.default_rng(9).normal(size=(3, N_FEATURES)).astype(np.float32)
    instance_bag = np.array([0, 1, 2], dtype=np.int64)

    u_esperado, _ = _u_torch(modelo, X, instance_bag, 3)
    resultado = predecir_numpy(pesos, X, instance_bag, 3)

    np.testing.assert_allclose(resultado["u"], u_esperado, rtol=1e-4, atol=1e-5)
    assert np.isfinite(resultado["u"]).all()


def test_extraer_pesos_leaves_out_the_dead_paths():
    """Solo viaja lo que `p_bag` usa. Medido en el modelo real, decoders,
    clasificadores, regresores y reliability heads son 61.268 de 150.926
    parametros que no participan de la prediccion bajo fusion='film'."""
    modelo = _modelo()

    pesos = extraer_pesos_mil(_PredictorFalso(modelo, _Geometria()))

    plano = repr(sorted(pesos.keys()))
    for muerto in ("decoder", "classifier", "regressor", "reliability"):
        assert muerto not in plano
    assert {m["nombre"] for m in pesos["modalidades"]} == {"climaticos", "estructurales"}
    # Los `Linear` viajan ya transpuestos, para que el consumidor haga `x @ W`.
    primera = pesos["modalidades"][0]["red"][0]
    assert primera["tipo"] == "linear" and primera["W"].shape == (7, HIDDEN_DIM)


def test_extraer_pesos_rejects_a_fusion_it_cannot_reproduce():
    """Exportar una fusion y calcular otra daria un numero plausible y
    equivocado: se prohibe en el exportador, no en el navegador."""
    modelo = _modelo()
    modelo.fusion = "reliability"

    with pytest.raises(ValueError, match="film"):
        extraer_pesos_mil(_PredictorFalso(modelo, _Geometria()))


def test_rango_efectivo_matches_the_svd_statistic():
    """El grafo se anula segun este numero. La via sin SVD tiene que dar lo
    MISMO que `estadistico_colapso`, no algo parecido."""
    generador = np.random.default_rng(7)
    for forma in [(12, 6), (3, 64), (40, 8)]:
        gates = generador.uniform(0.0, 2.0, size=forma)

        assert rango_efectivo(gates) == pytest.approx(
            estadistico_colapso(gates)["effective_rank"], rel=1e-9)


def test_rango_efectivo_of_identical_rows_collapses_to_zero():
    """Compuertas que no varian entre vanos: matriz centrada nula, energia 0.
    Es el caso que anula el panel del grafo, y tiene que decidirse igual que en
    Python en vez de dividir por cero."""
    gates = np.tile(np.array([0.4, 1.7, 0.9]), (5, 1))

    assert rango_efectivo(gates) == 0.0
    assert estadistico_colapso(gates)["is_collapsed"]


def test_clase_numpy_matches_asignar_clase():
    from chec_impacto.models.criticality_assignment import Geometria, asignar_clase

    g = _Geometria()
    geometria = Geometria(offset=g.offset, scale=g.scale, logs=g.logs,
                          centroides=g.centroides)
    n_obs = np.array([1.0, 4.0, 27.0, 3.0])
    u = np.array([0.5, 18.0, 300.0, -2.0])  # el negativo ejercita el clamp por eps

    esperado, _ = asignar_clase(n_obs, u, geometria)

    np.testing.assert_array_equal(
        clase_numpy(n_obs, u, {"offset": g.offset, "scale": g.scale, "logs": g.logs,
                               "centroides": g.centroides}),
        esperado)


def test_pesos_a_json_is_serialisable_and_keeps_shapes():
    import json

    pesos = extraer_pesos_mil(_PredictorFalso(_modelo(), _Geometria()))

    plano = pesos_a_json(pesos)
    texto = json.dumps(plano)  # falla si quedo un ndarray suelto

    assert len(texto) > 0
    # Cada capa conserva su `tipo` de operacion; el array viaja anidado, con su
    # propia forma, para que el consumidor pueda reconstruir el Float32Array.
    primera = plano["modalidades"][0]["red"][0]
    assert primera["tipo"] == "linear"
    assert primera["W"]["forma"] == [7, HIDDEN_DIM] and primera["W"]["tipo"] == "float32"
    assert plano["modalidades"][0]["indices"]["tipo"] == "int32"
