"""Unit tests for MIL bag construction (PR1 of notebook-10-mil-vano-ventana).

Bags are `(CIRCUITO, FID_VANO, window)` cells of 01.4; instances are event
rows. See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain
    `mil-bag-construction`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D1, D4)

Section headers below reference task numbers from
`sdd/notebook-10-mil-vano-ventana/tasks`, PR1 (`data/bags.py`).

1.5 and 1.6 exercise the REAL, untouched
`chec_impacto.data.graph.construir_matriz_adyacencia_mgcecdl` against the
frozen 70-feature order (`data/graphs/mgcecdl_feature_order.json`) -- they
pin the exact graph-deletion failure mode D4 replaces, not a new production
code path in this module. 1.6 additionally exercises the not-yet-implemented
`construir_matriz_instancias`, so it is genuinely RED until 1.7 lands it.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chec_impacto.data.graph import construir_matriz_adyacencia_mgcecdl

FROZEN_FEATURES_PATH = Path("data/graphs/mgcecdl_feature_order.json")

_LEAKY_COLUMNS = ("DURACION", "TOT_USUS", "UITI", "PORC_APORTE_VANO", "UITI_VANO")


def _frozen_features() -> list[str]:
    return json.loads(FROZEN_FEATURES_PATH.read_text())


def _matriz_base_no_degenerada(n_filas: int, n_columnas: int, seed: int = 42) -> np.ndarray:
    """A non-constant `(n_filas, n_columnas)` matrix -- every column has a
    positive std, so it never trips the B2 zero-variance guard by accident."""
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n_filas, n_columnas)).astype(np.float32)


def _df_causa_sintetico() -> pd.DataFrame:
    """A known tail: codes 1 (60%) and 2 (30%) clear a 5% threshold; codes
    3, 4 and 5 sit below it and collapse to `COD_CAUSA_OTRAS`."""
    codigos = [1] * 60 + [2] * 30 + [3] * 4 + [4] * 3 + [5] * 3
    return pd.DataFrame(
        {
            "COD_CAUSA": codigos,
            "UITI_VANO": np.linspace(1.0, 2.0, num=len(codigos)),
        }
    )


# ---------------------------------------------------------------------------
# 1.1 -- BagIndex.__post_init__ invariants
# ---------------------------------------------------------------------------


def test_bag_index_accepts_a_consistent_construction() -> None:
    from chec_impacto.data.bags import BagIndex

    instance_bag = np.array([0, 0, 1, 2, 2, 2], dtype=np.int64)
    bag_index = BagIndex(
        keys=pd.DataFrame(
            {"CIRCUITO": ["A", "A", "B"], "FID_VANO": ["1", "2", "3"], "VENTANA": ["w1"] * 3}
        ),
        instance_bag=instance_bag,
        offsets=np.array([0, 2, 3, 6], dtype=np.int64),
        counts=np.array([2, 1, 3], dtype=np.int64),
        y=np.array([10.0, 5.0, 30.0]),
        group=np.array(["A|1", "A|2", "B|3"], dtype=object),
        instance_rows=np.arange(6, dtype=np.int64),
    )

    assert bag_index.offsets[-1] == len(instance_bag)
    assert np.all(np.diff(bag_index.instance_bag) >= 0)
    assert bag_index.counts.sum() == len(instance_bag)


def test_bag_index_rejects_offsets_mismatch() -> None:
    from chec_impacto.data.bags import BagIndex

    with pytest.raises(ValueError, match="offsets"):
        BagIndex(
            keys=pd.DataFrame({"CIRCUITO": ["A"], "FID_VANO": ["1"], "VENTANA": ["w1"]}),
            instance_bag=np.array([0, 0], dtype=np.int64),
            offsets=np.array([0, 1], dtype=np.int64),  # should end at 2
            counts=np.array([2], dtype=np.int64),
            y=np.array([1.0]),
            group=np.array(["A|1"], dtype=object),
            instance_rows=np.arange(2, dtype=np.int64),
        )


def test_bag_index_rejects_non_monotonic_instance_bag() -> None:
    from chec_impacto.data.bags import BagIndex

    with pytest.raises(ValueError, match="instance_bag"):
        BagIndex(
            keys=pd.DataFrame(
                {"CIRCUITO": ["A", "B"], "FID_VANO": ["1", "2"], "VENTANA": ["w1", "w1"]}
            ),
            instance_bag=np.array([0, 1, 0], dtype=np.int64),  # decreases 1 -> 0
            offsets=np.array([0, 2, 3], dtype=np.int64),
            counts=np.array([2, 1], dtype=np.int64),
            y=np.array([1.0, 2.0]),
            group=np.array(["A|1", "B|2"], dtype=object),
            instance_rows=np.arange(3, dtype=np.int64),
        )


def test_bag_index_rejects_counts_sum_mismatch() -> None:
    from chec_impacto.data.bags import BagIndex

    with pytest.raises(ValueError, match="counts"):
        BagIndex(
            keys=pd.DataFrame({"CIRCUITO": ["A"], "FID_VANO": ["1"], "VENTANA": ["w1"]}),
            instance_bag=np.array([0, 0], dtype=np.int64),
            offsets=np.array([0, 2], dtype=np.int64),
            counts=np.array([3], dtype=np.int64),  # should be 2
            y=np.array([1.0]),
            group=np.array(["A|1"], dtype=object),
            instance_rows=np.arange(2, dtype=np.int64),
        )


# ---------------------------------------------------------------------------
# 1.2 -- construir_indice_bolsas over overlapping windows
# ---------------------------------------------------------------------------


def _eventos_sinteticos() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2", "C2"],
            "FID_VANO": ["V1", "V1", "V1", "V2", "V2"],
            "UITI_VANO": [10.0, 20.0, 5.0, 7.0, 3.0],
        }
    )


def test_construir_indice_bolsas_duplicates_events_that_fall_in_two_windows() -> None:
    from chec_impacto.data.bags import construir_indice_bolsas

    df = _eventos_sinteticos()
    # Event row 0 falls inside both windows of vano V1 -- the design's
    # documented overlap (11 windows of 01.4 overlap by construction).
    calendario = np.array([True, True, False, True, False])
    cruzada = np.array([True, False, False, False, True])

    bag_index = construir_indice_bolsas(df, [("calendario", calendario), ("cruzada", cruzada)])

    # 4 bags with events: (C1,V1,calendario)={0,1}, (C1,V1,cruzada)={0},
    # (C2,V2,calendario)={3}, (C2,V2,cruzada)={4}.
    assert len(bag_index.offsets) - 1 == 4
    assert bag_index.instance_rows.tolist().count(0) == 2
    # Row 2 is selected by neither window and never becomes an instance;
    # row 0 (value 10.0) is selected by both and is summed into two bags.
    valores_seleccionados = df.loc[[0, 1, 3, 4], "UITI_VANO"].sum()
    assert bag_index.y.sum() == pytest.approx(valores_seleccionados + 10.0)


def test_construir_indice_bolsas_keeps_a_vanos_overlapping_bags_in_one_group() -> None:
    from chec_impacto.data.bags import construir_indice_bolsas

    df = _eventos_sinteticos()
    calendario = np.array([True, True, False, True, False])
    cruzada = np.array([True, False, False, False, True])

    bag_index = construir_indice_bolsas(df, [("calendario", calendario), ("cruzada", cruzada)])

    v1_bag_positions = [i for i, g in enumerate(bag_index.group) if g == "C1|V1"]
    assert len(v1_bag_positions) == 2
    # Same CV group key for every bag of the same vano -> StratifiedGroupKFold
    # never splits a vano's overlapping bags across folds.
    assert {bag_index.group[i] for i in v1_bag_positions} == {"C1|V1"}


# ---------------------------------------------------------------------------
# 1.3 / 1.4 -- codificar_cod_causa
# ---------------------------------------------------------------------------


def test_codificar_cod_causa_threshold_and_otras_collapse() -> None:
    from chec_impacto.data.bags import codificar_cod_causa

    df_causa, encoding = codificar_cod_causa(_df_causa_sintetico(), min_frecuencia_relativa=0.05)

    assert encoding.codigos_propios == (1, 2)
    assert set(encoding.nombres_indicadores) == {"COD_CAUSA_1", "COD_CAUSA_2", "COD_CAUSA_OTRAS"}
    otras_mask = df_causa["COD_CAUSA_OTRAS"] == 1.0
    assert otras_mask.sum() == 10  # codes 3 (4 rows) + 4 (3 rows) + 5 (3 rows)
    assert (df_causa.loc[otras_mask, "COD_CAUSA_1"] == 0.0).all()


def test_codificar_cod_causa_indicator_rows_sum_to_one() -> None:
    from chec_impacto.data.bags import codificar_cod_causa

    df_causa, encoding = codificar_cod_causa(_df_causa_sintetico(), min_frecuencia_relativa=0.05)

    indicadores = df_causa[list(encoding.nombres_indicadores)]
    assert np.allclose(indicadores.sum(axis=1).to_numpy(), 1.0)


def test_codificar_cod_causa_frequency_column_is_target_free() -> None:
    from chec_impacto.data.bags import codificar_cod_causa

    df = _df_causa_sintetico()
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)

    assert encoding.nombre_frecuencia == "COD_CAUSA"
    df_shuffled_target = df.assign(UITI_VANO=df["UITI_VANO"].to_numpy()[::-1])
    _, encoding_shuffled = codificar_cod_causa(df_shuffled_target, min_frecuencia_relativa=0.05)
    assert encoding.frecuencias == encoding_shuffled.frecuencias

    valores_codigo_1 = df_causa.loc[df["COD_CAUSA"] == 1, "COD_CAUSA"].unique()
    assert valores_codigo_1 == pytest.approx([0.60])


def test_codificar_cod_causa_routes_to_structural_modality() -> None:
    from chec_impacto.data.bags import codificar_cod_causa
    from chec_impacto.training.mgcecdl import es_variable_exogena_mgcecdl

    _, encoding = codificar_cod_causa(_df_causa_sintetico(), min_frecuencia_relativa=0.05)

    assert es_variable_exogena_mgcecdl(encoding.nombre_frecuencia) is False
    for nombre in encoding.nombres_indicadores:
        assert es_variable_exogena_mgcecdl(nombre) is False


# ---------------------------------------------------------------------------
# 1.5 -- negative pin: renaming COD_CAUSA deletes the graph node
# ---------------------------------------------------------------------------


def test_renaming_cod_causa_column_deletes_the_graph_node() -> None:
    """Pins the exact failure mode D4 replaces: naming the encoded column
    `COD_CAUSA_28` instead of `COD_CAUSA` makes `construir_aristas_preservadas`
    treat the real `COD_CAUSA` node as removed (`data/graph.py:124,130-141`),
    so the dummy column ends up isolated and E stays at the baseline 56
    (measured against the real graph, obs #532)."""
    features = _frozen_features()
    _, edges_sin = construir_matriz_adyacencia_mgcecdl(features)
    assert len(edges_sin) == 56

    features_renombrado = [*features, "COD_CAUSA_28"]
    matrix_renombrado, edges_renombrado = construir_matriz_adyacencia_mgcecdl(features_renombrado)

    position = len(features_renombrado) - 1
    assert len(edges_renombrado) == 56
    assert int((matrix_renombrado[:, position] != 0).sum()) == 0
    assert int((matrix_renombrado[position, :] != 0).sum()) == 0


# ---------------------------------------------------------------------------
# 1.6 / 1.7 -- construir_matriz_instancias preserves the COD_CAUSA graph node
# ---------------------------------------------------------------------------


def test_construir_matriz_instancias_output_features_preserve_the_8_cod_causa_edges() -> None:
    from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias

    features = _frozen_features()
    df = _df_causa_sintetico()
    resultado = {"X": _matriz_base_no_degenerada(len(df), len(features)), "features": features}
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)

    _, features_out = construir_matriz_instancias(resultado, df_causa, encoding, features)

    matrix, edges = construir_matriz_adyacencia_mgcecdl(features_out)
    position = features_out.index("COD_CAUSA")
    in_edges = {features_out[i] for i in range(len(features_out)) if matrix[i, position] != 0}

    assert in_edges == {
        "LONGITUD",
        "CONDUCTOR",
        "NR_T",
        "DDT",
        "prep_0",
        "temp_0",
        "wind_gust_spd_0",
        "wind_spd_0",
    }
    assert int((matrix[position, :] != 0).sum()) == 0  # pure sink
    assert len(edges) == 64

    for nombre in encoding.nombres_indicadores:
        indicator_position = features_out.index(nombre)
        assert int((matrix[:, indicator_position] != 0).sum()) == 0
        assert int((matrix[indicator_position, :] != 0).sum()) == 0


def test_construir_matriz_instancias_names_cod_causa_column_exactly_once() -> None:
    from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias

    features = _frozen_features()
    df = _df_causa_sintetico()
    resultado = {"X": _matriz_base_no_degenerada(len(df), len(features)), "features": features}
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)

    _, features_out = construir_matriz_instancias(resultado, df_causa, encoding, features)

    assert features_out.count("COD_CAUSA") == 1


# ---------------------------------------------------------------------------
# 1.8 / 1.9 -- A5 algebraic-leakage hard assertion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("leaky_column", _LEAKY_COLUMNS)
def test_construir_matriz_instancias_halts_on_algebraic_leakage(leaky_column: str) -> None:
    from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias

    df = _df_causa_sintetico()
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)
    leaky_features = ["LONGITUD", leaky_column]
    resultado = {
        "X": np.zeros((len(df), len(leaky_features)), dtype=np.float32),
        "features": leaky_features,
    }

    with pytest.raises(ValueError, match=leaky_column):
        construir_matriz_instancias(resultado, df_causa, encoding, leaky_features)


def test_construir_matriz_instancias_passes_when_no_leaky_column_present() -> None:
    from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias

    features = _frozen_features()
    df = _df_causa_sintetico()
    resultado = {"X": _matriz_base_no_degenerada(len(df), len(features)), "features": features}
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)

    _, features_out = construir_matriz_instancias(resultado, df_causa, encoding, features)

    assert all(columna not in features_out for columna in _LEAKY_COLUMNS)


# ---------------------------------------------------------------------------
# 1.10 / 1.11 -- B2 cardinality-signal guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden_column", ["num_eventos", "counts"])
def test_construir_matriz_instancias_halts_on_cardinality_signal(forbidden_column: str) -> None:
    from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias

    df = _df_causa_sintetico()
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)
    tainted_features = ["LONGITUD", forbidden_column]
    resultado = {
        "X": np.zeros((len(df), len(tainted_features)), dtype=np.float32),
        "features": tainted_features,
    }

    with pytest.raises(ValueError, match=forbidden_column):
        construir_matriz_instancias(resultado, df_causa, encoding, tainted_features)


def test_construir_matriz_instancias_every_column_has_positive_std() -> None:
    from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias

    features = _frozen_features()
    df = _df_causa_sintetico()
    rng = np.random.default_rng(42)
    X = rng.normal(size=(len(df), len(features))).astype(np.float32)
    resultado = {"X": X, "features": features}
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)

    X_inst, _ = construir_matriz_instancias(resultado, df_causa, encoding, features)

    assert np.all(X_inst.std(axis=0) > 0)


def test_construir_matriz_instancias_rejects_a_degenerate_constant_column() -> None:
    from chec_impacto.data.bags import codificar_cod_causa, construir_matriz_instancias

    features = ["LONGITUD"]
    df = _df_causa_sintetico()
    X = np.zeros((len(df), 1), dtype=np.float32)  # constant column -> std == 0
    resultado = {"X": X, "features": features}
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)

    with pytest.raises(ValueError, match="std"):
        construir_matriz_instancias(resultado, df_causa, encoding, features)


# ---------------------------------------------------------------------------
# 1.12 / 1.13 -- cachear_bolsas / cargar_bolsas round-trip
# ---------------------------------------------------------------------------


def test_cachear_bolsas_and_cargar_bolsas_roundtrip(tmp_path: Path) -> None:
    from chec_impacto.data.bags import (
        cachear_bolsas,
        cargar_bolsas,
        codificar_cod_causa,
        construir_indice_bolsas,
        construir_matriz_instancias,
    )

    features = _frozen_features()
    df = _df_causa_sintetico()
    resultado = {"X": _matriz_base_no_degenerada(len(df), len(features)), "features": features}
    df_causa, encoding = codificar_cod_causa(df, min_frecuencia_relativa=0.05)
    X_inst, features_out = construir_matriz_instancias(resultado, df_causa, encoding, features)

    df_causa_con_llaves = df_causa.assign(CIRCUITO="C1", FID_VANO="V1")
    ventana = np.ones(len(df), dtype=bool)
    bag_index = construir_indice_bolsas(df_causa_con_llaves, [("w1", ventana)])

    cache_path = tmp_path / "derived" / "bolsas.joblib"
    written = cachear_bolsas(cache_path, X_inst, bag_index, features_out, encoding)

    assert written == cache_path
    assert cache_path.exists()

    cargado = cargar_bolsas(cache_path)

    assert np.array_equal(cargado["X"], X_inst)
    assert cargado["features"] == features_out
    assert np.array_equal(cargado["bag_index"].instance_bag, bag_index.instance_bag)
    assert np.array_equal(cargado["bag_index"].offsets, bag_index.offsets)
    assert cargado["encoding"].codigos_propios == encoding.codigos_propios


def test_cargar_bolsas_raises_on_missing_cache(tmp_path: Path) -> None:
    from chec_impacto.data.bags import cargar_bolsas

    with pytest.raises(FileNotFoundError):
        cargar_bolsas(tmp_path / "does_not_exist.joblib")
