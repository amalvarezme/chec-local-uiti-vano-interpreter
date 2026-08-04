"""Row-2 (predicted map) simulator wiring support for notebook 01.5 (PR5).

Everything a live kernel needs that is decidable WITHOUT ipywidgets, a model, or a
running event loop lives here, unit-tested without any of them -- the same split
PR1-PR4 established: notebook cells only call already-tested functions.

Covers design section A's three pieces that make the debounce machinery safe:

- **The epoch guard** (`siguiente_epoca` / `aplicar_si_vigente`): a trailing debounce
  alone does not stop a slow job finishing after a newer one -- the epoch guard is
  what discards that stale write. `asyncio.ensure_future` (never `threading.Timer`,
  since ipykernel's parent header is thread-local) drives the actual debounce in the
  notebook cell; this module owns only the pure epoch-comparison logic that runs
  inside it.
- **The degradation ladder's first rung** (`submuestrear_si_excede`): a deterministic
  `default_rng(42)` subsample above `FILAS_MAX_INTERACTIVO` rows, so tier 1/2 stay
  within their latency budget regardless of window size.
- **The degradation ladder's second rung** (`debe_degradar_a_manual`): whether a
  MEASURED tier-2 duration should auto-switch ranking from automatic to manual (task
  5.9 records one real number on this machine and may adjust `UMBRAL_DEGRADACION_SEGUNDOS`
  accordingly).
- **The base/simulado/delta toggle's 3-state read** (`clases_por_fid_para_estado`,
  `bin_delta_riesgo`): all three states are read from ONE `simulate_explicit_overrides`
  call's output (design section C) -- zero extra forward passes for the toggle. Delta
  is binned into the SAME 4-slot shape `capas_mapa_historico` already groups classes
  into, so row 2's map repaint code is identical for every toggle state.
- **The event-row mask cache** (`construir_evento_mask_cache`): PR5's own
  `(circuito, ventana_i) -> boolean mask` over `context_df`'s RAW event rows -- the
  row space `simulate_explicit_overrides` needs (row-aligned with `X`/`X_scaled`).
  A SEPARATE cache from `ventanas_015.construir_mask_cache` (TABLA-scoped) and from
  `relevancias_015`'s own private one (marked-vano scoped): PR5's needs the FULL
  circuit+window mask, not a marked-vano subset, so it is not a fit for either
  existing cache and is built independently here, mirroring why `relevancias_015`
  built its own rather than reusing PR3's.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-risk-simulation`, "Row 2 anti-conflation and base/simulado/delta
    toggle")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section A, section G)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

DEBOUNCE_SEGUNDOS = 0.35
FILAS_MAX_INTERACTIVO = 20_000
# design's modelled p50 target was 4.0s for tier 2 (53 passes, <=8 marked vanos); this
# threshold is the SEPARATE degradation trigger (design's ladder rung 2, "measured
# duration > 6s"). Task 5.9 measured one real number on this machine and confirmed 6.0s
# still holds -- see apply-progress for the recorded measurement.
UMBRAL_DEGRADACION_SEGUNDOS = 6.0

ESTADO_BASE = "base"
ESTADO_SIMULADO = "simulado"
ESTADO_DELTA = "delta"

ETIQUETAS_ALTERNADOR: tuple[str, str, str] = (
    "Predicho (base)",
    "Predicho (simulado)",
    "Δ simulado − base",
)
ESTADO_POR_ETIQUETA: dict[str, str] = {
    "Predicho (base)": ESTADO_BASE,
    "Predicho (simulado)": ESTADO_SIMULADO,
    "Δ simulado − base": ESTADO_DELTA,
}
ALTERNADOR_POR_DEFECTO = "Predicho (simulado)"

# Bucket labels for the delta toggle state, index-aligned with `bin_delta_riesgo`'s
# return value (0-3) -- the "swapped legend" design section G calls for.
ETIQUETAS_DELTA: tuple[str, str, str, str] = (
    "Δ <= -0.5 (mejora fuerte)",
    "Δ < 0 (mejora)",
    "Δ > 0 (empeora)",
    "Δ >= +0.5 (empeora fuerte)",
)


# --- Epoch guard (design section A) -----------------------------------------------------


def siguiente_epoca(epoca_actual: int) -> int:
    """One monotonic step. Every event that can invalidate an in-flight tier-1/tier-2
    job (selection change, "Simular" press, toggle change) bumps the SAME shared
    epoch -- this is what lets a stale job be discarded regardless of which tier
    started it."""
    return epoca_actual + 1


def aplicar_si_vigente(
    escritura: Callable[[], Any],
    *,
    epoca_job: int,
    epoca_actual: Callable[[], int],
) -> bool:
    """Runs `escritura` (a figure repaint / status update) ONLY if `epoca_job` still
    equals the epoch at write time. A stale job -- one whose epoch was superseded by a
    newer event while it was computing -- is discarded silently: `escritura` is never
    called, and whatever the newer job already painted is left untouched. This is the
    piece a trailing debounce alone cannot provide: the debounce prevents most stale
    jobs from ever STARTING, but a job already running cannot be pre-empted (design
    section A), so the write itself needs its own guard. Returns whether the write
    happened."""
    if epoca_job != epoca_actual():
        return False
    escritura()
    return True


# --- Degradation ladder (design section A) -----------------------------------------------


def submuestrear_si_excede(
    mask: np.ndarray, *, limite: int = FILAS_MAX_INTERACTIVO, semilla: int = 42
) -> tuple[np.ndarray, bool, int]:
    """Degradation ladder rung 1: above `limite` masked rows, deterministically
    subsample down to exactly `limite` rows via `np.random.default_rng(semilla)` --
    the SAME seed every call, so repeated calls over the same mask choose the exact
    same subset (reproducible, not merely "some random sample"). Below or at `limite`,
    `mask` is returned unchanged. Returns `(mask_efectiva, submuestreado, n_total)`."""
    mask = np.asarray(mask, dtype=bool)
    n_total = int(mask.sum())
    if n_total <= limite:
        return mask, False, n_total
    indices = np.flatnonzero(mask)
    rng = np.random.default_rng(semilla)
    elegidos = rng.choice(indices, size=limite, replace=False)
    mask_efectiva = np.zeros_like(mask)
    mask_efectiva[elegidos] = True
    return mask_efectiva, True, n_total


def debe_degradar_a_manual(
    duracion_segundos: float, *, umbral: float = UMBRAL_DEGRADACION_SEGUNDOS
) -> bool:
    """Degradation ladder rung 2: a MEASURED tier-2 duration over `umbral` seconds
    means automatic ranking should switch itself off (design: "auto-uncheck
    `Relevancias automaticas`... switch to a manual `Recalcular relevancias` button"),
    rather than keep firing a multi-second recompute on every marked-vano change."""
    return duracion_segundos > umbral


# --- Base/simulado/delta toggle (design section C, section G) ----------------------------


def bin_delta_riesgo(delta: float) -> int:
    """Bucket a `delta_riesgo_ordinal` value into one of 4 indices matching the design's
    stated bins (`<=-0.5`, `<0`, `>0`, `>=+0.5`), checked in severity order so the
    boundaries never overlap. Reuses the SAME 4-slot shape as the class layers (0-3)
    so `capas_mapa_historico` can draw either state without a second grouping
    function -- only the legend text differs (`ETIQUETAS_DELTA` vs. the class names)."""
    if delta <= -0.5:
        return 0
    if delta < 0:
        return 1
    if delta >= 0.5:
        return 3
    return 2  # 0 <= delta < 0.5 (includes the exact-zero case: "no meaningful change")


def clases_por_fid_desde_resultado(tabla_resultado: pd.DataFrame, columna: str) -> dict[str, int]:
    """`FID_VANO -> int(columna)` from a `simulate_explicit_overrides` result row, one
    entry per row. Keys are always coerced to `str`: `simulate_explicit_overrides`
    already stringifies `FID_VANO` internally (via its own `base_vanos.astype(str)`),
    this is belt-and-braces so callers never depend on that staying true."""
    return {str(row["FID_VANO"]): int(row[columna]) for _, row in tabla_resultado.iterrows()}


def clases_por_fid_para_estado(tabla_resultado: pd.DataFrame, estado: str) -> dict[str, int]:
    """`FID_VANO -> class-layer index (0-3)` for row 2's 3-state toggle. `base` and
    `simulado` read the model's own class column directly; `delta` bins
    `delta_riesgo_ordinal` via `bin_delta_riesgo` first. All three read the SAME
    `tabla_resultado` -- the one DataFrame `simulate_explicit_overrides` already
    returned -- so the toggle never triggers another forward pass (design section C).
    An unknown `estado` raises `ValueError`: a silently-empty map would look
    indistinguishable from "sin dato", which is exactly what D2's anti-conflation
    requirement says must never happen."""
    if estado == ESTADO_BASE:
        return clases_por_fid_desde_resultado(tabla_resultado, "base_clase_idx")
    if estado == ESTADO_SIMULADO:
        return clases_por_fid_desde_resultado(tabla_resultado, "simulado_clase_idx")
    if estado == ESTADO_DELTA:
        tabla_con_bin = tabla_resultado.assign(
            _delta_bin=tabla_resultado["delta_riesgo_ordinal"].map(bin_delta_riesgo)
        )
        return clases_por_fid_desde_resultado(tabla_con_bin, "_delta_bin")
    raise ValueError(f"Estado de alternador desconocido: {estado!r}")


# --- Row 2's `sin_dato` trace: two absence-reasons, two labels (verify finding W1) -------

# `capas_mapa_historico` (shared with row 1) buckets any fid absent from `clases_por_fid`
# into ONE `sin_dato` layer. Row 2 feeds it `{}` in two genuinely different situations:
# before the first "Simular" press (no simulation exists yet for the active selection)
# and after a simulation whose result table simply has no row for a given vano (zero
# event-rows in the active window). D2's anti-conflation rule says one visual signal must
# not carry two meanings, so the two states get two different legend labels -- the
# notebook cell pairs each with a different trace colour too (`COLOR_SIN_DATO` vs. its own
# `COLOR_AUN_NO_SIMULADO`, both notebook-owned constants matching 01.4's palette
# convention). This restyles the EXISTING `pred_sin_dato` trace (idx 12, design section G)
# on every repaint -- it does not add a trace.
ETIQUETA_SIN_DATO = "Sin dato"
ETIQUETA_AUN_NO_SIMULADO = "Aun no simulado"


def etiqueta_capa_sin_dato(hay_resultado: bool) -> str:
    """Legend label for row 2's `sin_dato` trace, disambiguating the two absence-reasons
    a fid can land in that bucket for: `hay_resultado=False` means no simulation exists
    yet for the active selection (every vano is "aun no simulado"); `hay_resultado=True`
    means a simulation ran and this specific vano has zero event-rows in the active
    window ("sin dato"). Never returns the same label for both -- an unlabelled or
    identically-labelled state would silently recreate the exact ambiguity D2 exists to
    prevent."""
    return ETIQUETA_SIN_DATO if hay_resultado else ETIQUETA_AUN_NO_SIMULADO


# --- Event-row mask cache, owned by PR5 (design section A) -------------------------------


def construir_evento_mask_cache(
    context_df: pd.DataFrame, ventanas: Sequence[Mapping[str, Any]], *, maxsize: int = 64
) -> Callable[[str, int], np.ndarray]:
    """`(circuito, ventana_i) -> boolean mask` over `context_df`'s RAW event rows,
    row-aligned with `X`/`X_scaled` -- the row space `simulate_explicit_overrides`
    needs for row 2's FULL circuit+window map (not a marked-vano subset, unlike
    `relevancias_015`'s own private mask cache)."""
    fechas = pd.to_datetime(context_df["FECHA"]).to_numpy()
    circuitos = context_df["CIRCUITO"].astype(str).to_numpy()
    ventanas_por_i = {int(v["i"]): v for v in ventanas}

    @lru_cache(maxsize=maxsize)
    def mask_para(circuito: str, ventana_i: int) -> np.ndarray:
        ventana = ventanas_por_i[int(ventana_i)]
        desde = np.datetime64(pd.Timestamp(ventana["desde"]))
        hasta_excl = np.datetime64(pd.Timestamp(ventana["hasta_excl"]))
        return (circuitos == circuito) & (fechas >= desde) & (fechas < hasta_excl)

    return mask_para
