"""RED/GREEN tests for notebook 01.5's `vano_app_015` module (PR5).

Covers row 2's pure support functions -- the epoch guard and the degradation
ladder (design section A), the base/simulado/delta toggle's 3-state read
(design section C), and PR5's own event-row mask cache. Everything a live
kernel needs is tested here WITHOUT ipywidgets, a model, or a running event
loop -- the notebook cell only calls these already-tested functions (the
same split PR1-PR4 established).

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-risk-simulation`, "Row 2 anti-conflation and
    base/simulado/delta toggle")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section A, section C, section G)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chec_local_interpreter.vano_app_015 import (
    ESTADO_BASE,
    ESTADO_DELTA,
    ESTADO_SIMULADO,
    FILAS_MAX_INTERACTIVO,
    aplicar_si_vigente,
    bin_delta_riesgo,
    clases_por_fid_desde_resultado,
    clases_por_fid_para_estado,
    construir_evento_mask_cache,
    debe_degradar_a_manual,
    siguiente_epoca,
    submuestrear_si_excede,
)

# --- 5.1 RED/GREEN: epoch guard discards a stale job completion --------------------------


def test_siguiente_epoca_is_one_monotonic_step():
    assert siguiente_epoca(0) == 1
    assert siguiente_epoca(41) == 42


def test_aplicar_si_vigente_discards_a_stale_write_on_epoch_mismatch():
    escrituras = []
    ok = aplicar_si_vigente(
        lambda: escrituras.append("deberia-descartarse"),
        epoca_job=1,
        epoca_actual=lambda: 2,  # a newer event already bumped the epoch
    )
    assert ok is False
    assert escrituras == []  # the write NEVER ran -- proves the guard, not just the return value


def test_aplicar_si_vigente_runs_the_write_when_the_epoch_still_matches():
    escrituras = []
    ok = aplicar_si_vigente(
        lambda: escrituras.append("vigente"),
        epoca_job=3,
        epoca_actual=lambda: 3,
    )
    assert ok is True
    assert escrituras == ["vigente"]


# --- 5.2 RED/GREEN: degradation ladder subsamples deterministically ----------------------


def test_submuestrear_si_excede_subsamples_above_the_limit():
    mask = np.ones(FILAS_MAX_INTERACTIVO + 500, dtype=bool)
    mask_efectiva, submuestreado, n_total = submuestrear_si_excede(mask, limite=1_000, semilla=42)
    assert submuestreado is True
    assert n_total == FILAS_MAX_INTERACTIVO + 500
    assert int(mask_efectiva.sum()) == 1_000


def test_submuestrear_si_excede_is_deterministic_across_calls():
    mask = np.zeros(5_000, dtype=bool)
    mask[::2] = True  # 2500 candidate rows, well above a small limit
    primero, _, _ = submuestrear_si_excede(mask, limite=100, semilla=42)
    segundo, _, _ = submuestrear_si_excede(mask, limite=100, semilla=42)
    assert np.array_equal(primero, segundo)  # SAME seed -> SAME chosen subset, every call


def test_submuestrear_si_excede_leaves_a_mask_under_the_limit_unchanged():
    mask = np.array([True, False, True, True, False])
    mask_efectiva, submuestreado, n_total = submuestrear_si_excede(mask, limite=10)
    assert submuestreado is False
    assert n_total == 3
    assert np.array_equal(mask_efectiva, mask)


def test_debe_degradar_a_manual_true_above_threshold_false_below():
    assert debe_degradar_a_manual(6.5, umbral=6.0) is True
    assert debe_degradar_a_manual(5.9, umbral=6.0) is False


# --- Base/simulado/delta toggle --------------------------------------------------------


@pytest.mark.parametrize(
    "delta, esperado",
    [
        (-1.0, 0),   # <= -0.5
        (-0.5, 0),   # boundary, inclusive
        (-0.3, 1),   # < 0
        (0.0, 2),    # exact zero -- "no meaningful change" bucket
        (0.3, 2),    # 0 <= delta < 0.5
        (0.5, 3),    # boundary, inclusive
        (2.0, 3),    # >= +0.5
    ],
)
def test_bin_delta_riesgo_covers_all_four_buckets(delta, esperado):
    assert bin_delta_riesgo(delta) == esperado


def _tabla_resultado():
    return pd.DataFrame(
        {
            "FID_VANO": [20130434, "v2"],  # mixed dtypes on purpose (production is int64)
            "base_clase_idx": [0, 3],
            "simulado_clase_idx": [1, 2],
            "delta_riesgo_ordinal": [1.0, -0.6],
        }
    )


def test_clases_por_fid_desde_resultado_stringifies_fid_keys():
    resultado = clases_por_fid_desde_resultado(_tabla_resultado(), "base_clase_idx")
    assert resultado == {"20130434": 0, "v2": 3}


def test_clases_por_fid_para_estado_base_reads_base_clase_idx():
    resultado = clases_por_fid_para_estado(_tabla_resultado(), ESTADO_BASE)
    assert resultado == {"20130434": 0, "v2": 3}


def test_clases_por_fid_para_estado_simulado_reads_simulado_clase_idx():
    resultado = clases_por_fid_para_estado(_tabla_resultado(), ESTADO_SIMULADO)
    assert resultado == {"20130434": 1, "v2": 2}


def test_clases_por_fid_para_estado_delta_bins_delta_riesgo_ordinal():
    resultado = clases_por_fid_para_estado(_tabla_resultado(), ESTADO_DELTA)
    assert resultado == {"20130434": 3, "v2": 0}  # 1.0 -> bucket 3, -0.6 -> bucket 0


def test_clases_por_fid_para_estado_rejects_an_unknown_toggle_value():
    with pytest.raises(ValueError, match="alternador"):
        clases_por_fid_para_estado(_tabla_resultado(), "no-es-un-estado-valido")


# --- Event-row mask cache ---------------------------------------------------------------


def _context_df():
    return pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1", "C2"],
            "FID_VANO": ["v1", "v2", "v3", "v4"],
            "FECHA": pd.to_datetime(["2024-01-05", "2024-01-20", "2024-02-05", "2024-01-05"]),
        }
    )


def _ventanas():
    return [
        {"i": 0, "desde": pd.Timestamp("2024-01-01"), "hasta_excl": pd.Timestamp("2024-02-01")},
        {"i": 1, "desde": pd.Timestamp("2024-02-01"), "hasta_excl": pd.Timestamp("2024-03-01")},
    ]


def test_construir_evento_mask_cache_selects_rows_inside_the_window_for_the_circuit():
    mask_para = construir_evento_mask_cache(_context_df(), _ventanas())
    mask = mask_para("C1", 0)
    assert mask.tolist() == [True, True, False, False]  # v1/v2 in window 0, v3 in window 1, v4 is C2


def test_construir_evento_mask_cache_upper_bound_is_exclusive():
    mask_para = construir_evento_mask_cache(_context_df(), _ventanas())
    mask_ventana_1 = mask_para("C1", 1)
    assert mask_ventana_1.tolist() == [False, False, True, False]  # only v3 (2024-02-05)


def test_construir_evento_mask_cache_returns_all_false_for_a_circuit_absent_from_the_window():
    mask_para = construir_evento_mask_cache(_context_df(), _ventanas())
    mask = mask_para("C2", 1)  # C2 only has a row in window 0
    assert mask.tolist() == [False, False, False, False]
    assert mask.any() is np.False_
