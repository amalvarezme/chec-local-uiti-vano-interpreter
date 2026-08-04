"""Ranked relevance panel support for notebook 01.5 (PR4).

Row 1 col 2 of the frozen figure (design section G, `IDX['ranking']` == 6)
shows a horizontal-bar ranking of "sensibilidad min-max" -- automatic
min/max sensitivity, via `simulator.simulate_automatic_minmax_sensitivity`
-- over the event-rows of the vanos MARKED in the active window (decision
D7). This is deliberately NOT Kernel SHAP (decision D5): every label this
module produces says "sensibilidad min-max", never "SHAP".

Ranking runs over one representative feature per `Knob` (design's
technical-approach section, "One organising abstraction unifies D6, B and
C"): 22 static knobs each contribute their own single feature, and each of
the 4 climate-family knobs contributes its first lag feature
(`knob.feature_names[0]`) as a stand-in for the whole family. That is what
cuts the cost model from the proposal's 141 passes (70 raw features) down
to `2*26 + 1 = 53` (design section A) -- ranking is a proxy for "which
control matters", not a fan-out simulation. The "Simular" button (PR5)
still fans a knob out to all its features via `expand_knob_overrides`,
unaffected by this simplification.

Caching (design section A):
  - `relevance_cache`: session-scoped, LRU 32, keyed by
    `(circuito, ventana_i, marked_key)`.
  - disk cache at `data/derived/relevancias_015/{slug}/{ventana}.json`,
    restricted to the ALL-VANOS key -- persisting an arbitrary marked-vano
    subset would mean persisting a powerset, which design section A
    rejects deliberately.
  - both are invalidated by a `fingerprint` mismatch
    (`sha1(geometrias_sha1, model sha256[:12], feature_names,
    ventana_climatica_horas, knob_catalog_version)`) -- the mechanism that
    stops a stale cache surviving a future MIL model swap (decision D1).

`{slug}` is derived from the circuit name the same shape as
`simulator.safe_plot_filename`: a name containing `/`, `\\` or `..` must
not escape the cache directory (design section A, the threat matrix's one
applicable case).

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-explainability-panel`, "Relevance ranking...")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section A)
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from chec_local_interpreter.simulator import simulate_automatic_minmax_sensitivity
from chec_local_interpreter.vano_controls import Knob

MARCADOS_TODOS = "__TODOS__"
KNOB_CATALOG_VERSION = 1
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "derived" / "relevancias_015"
MENSAJE_SIN_MARCADOS = "Marca uno o mas vanos en el mapa para calcular la sensibilidad min-max."
MENSAJE_SIN_FILAS = "No hay filas de evento para los vanos marcados en esta ventana."


def _slug(circuito: str) -> str:
    """Path-safe slug for a circuit name, same shape as
    `simulator.safe_plot_filename`: anything that is not `[A-Za-z0-9_-]`
    collapses to `_` and leading/trailing `_` are trimmed. `/`, `\\` and
    `..` never survive, so the resulting single path segment can never
    escape the cache directory it is joined into."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(circuito)).strip("_")
    return slug or "circuito"


def marked_key(marcados: Iterable[str], todos_en_ventana: Iterable[str]) -> str | tuple[str, ...]:
    """`relevance_cache`'s third key component (design section A):
    `"__TODOS__"` when the marked set equals the window's full vano set,
    else the sorted tuple of marked FIDs. An empty marked set is never
    `"__TODOS__"` (the caller handles the empty case before reaching the
    cache at all)."""
    marcados_set = {str(m) for m in marcados}
    todos_set = {str(t) for t in todos_en_ventana}
    if marcados_set and marcados_set == todos_set:
        return MARCADOS_TODOS
    return tuple(sorted(marcados_set))


def fingerprint(
    *,
    geometrias_sha1: str,
    model_path: str | Path,
    feature_names: Sequence[str],
    ventana_climatica_horas: int,
    knob_catalog_version: int = KNOB_CATALOG_VERSION,
) -> str:
    """The cache-busting mechanism (design section A): a change to 01.4's
    geometry, the loaded model file, the feature order, the climate
    window, or the knob catalog itself invalidates every cached ranking --
    the mechanism that stops a stale cache surviving the future MIL model
    swap (decision D1)."""
    model_sha256 = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()[:12]
    payload = "|".join(
        [
            str(geometrias_sha1),
            model_sha256,
            ",".join(str(name) for name in feature_names),
            str(ventana_climatica_horas),
            str(knob_catalog_version),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _ruta_cache_todos(circuito: str, ventana_i: int, *, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> Path:
    """Disk cache path for the ALL-VANOS key only (design section A):
    `data/derived/relevancias_015/{slug}/{ventana}.json`."""
    return Path(cache_dir) / _slug(circuito) / f"{int(ventana_i)}.json"


def _cargar_cache_disco(ruta: Path, *, fingerprint_actual: str) -> list[dict[str, Any]] | None:
    """Reads a disk-cached ranking and discards it (returns `None`) when
    the file is missing, unreadable, or its stored fingerprint does not
    match `fingerprint_actual`."""
    if not ruta.exists():
        return None
    try:
        payload = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("fingerprint") != fingerprint_actual:
        return None
    return payload.get("filas")


def _guardar_cache_disco(ruta: Path, filas: list[dict[str, Any]], *, fingerprint_actual: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps({"fingerprint": fingerprint_actual, "filas": filas}, ensure_ascii=False),
        encoding="utf-8",
    )


def _variable_representativa_por_knob(knobs: Sequence[Knob]) -> dict[str, str]:
    """One representative feature per knob: the knob's own first
    `feature_names` entry. For a static knob this IS its only feature; for
    a climate-family knob it stands in for the whole family in the ranking
    (see module docstring) -- unrelated to how "Simular" (PR5) fans a
    family out to all 12 lags via `expand_knob_overrides`."""
    return {knob.id: knob.feature_names[0] for knob in knobs if knob.feature_names}


def _filas_desde_tabla(
    tabla_resultado: pd.DataFrame,
    variable_por_knob: Mapping[str, str],
    knobs_por_id: Mapping[str, Knob],
) -> list[dict[str, Any]]:
    variable_a_knob: dict[str, str] = {}
    for knob_id, variable in variable_por_knob.items():
        variable_a_knob.setdefault(variable, knob_id)

    filas: list[dict[str, Any]] = []
    for _, row in tabla_resultado.iterrows():
        knob_id = variable_a_knob.get(str(row["variable"]))
        if knob_id is None:
            continue
        knob = knobs_por_id[knob_id]
        filas.append(
            {
                "knob_id": knob_id,
                "label": knob.label,
                "magnitud_max_cambio_abs": float(row["magnitud_max_cambio_abs"]),
                "direccion_maximo": str(row["direccion_cambio_maximo"]),
                "direccion_minimo": str(row["direccion_cambio_minimo"]),
            }
        )
    filas.sort(key=lambda fila: fila["magnitud_max_cambio_abs"], reverse=True)
    return filas


def _construir_evento_mask_cache(
    context_df: pd.DataFrame, ventanas: Sequence[Mapping[str, Any]], *, maxsize: int = 64
) -> Callable[[str, int], np.ndarray]:
    """`(circuito, ventana_i) -> boolean mask`, but over `context_df`'s RAW
    event rows -- row-aligned with `X`/`X_scaled`, one row per observed
    event, per `procesar_dataset_completo`'s `df_original_copy`. This is a
    DIFFERENT row space than `ventanas_015.construir_mask_cache`'s: that
    one indexes `TABLA`, the per-(vano, ventana) AGGREGATED table (one row
    per vano x window). `simulate_automatic_minmax_sensitivity`'s `mask`
    argument needs the former -- one boolean per raw event row -- so this
    module builds its own, rather than reusing PR3's TABLA-scoped cache."""
    fechas = pd.to_datetime(context_df["FECHA"]).to_numpy()
    circuitos = context_df["CIRCUITO"].astype(str).to_numpy()
    ventanas_por_i = {int(v["i"]): v for v in ventanas}

    @lru_cache(maxsize=maxsize)
    def mask_ventana_para(circuito: str, ventana_i: int) -> np.ndarray:
        ventana = ventanas_por_i[int(ventana_i)]
        desde = np.datetime64(pd.Timestamp(ventana["desde"]))
        hasta_excl = np.datetime64(pd.Timestamp(ventana["hasta_excl"]))
        return (circuitos == circuito) & (fechas >= desde) & (fechas < hasta_excl)

    return mask_ventana_para


def construir_relevance_cache(
    *,
    model: Any,
    X_scaled: np.ndarray,
    X_raw_model: np.ndarray,
    original_feature_df: pd.DataFrame,
    feature_names: Sequence[str],
    knobs: Sequence[Knob],
    feature_scaler: Any,
    predict_fn: Callable[..., dict[str, Any]],
    device: str,
    context_df: pd.DataFrame,
    ventanas: Sequence[Mapping[str, Any]],
    fingerprint_actual: str,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    maxsize: int = 32,
    batch_size: int = 1024,
) -> Callable[[str, int, Iterable[str]], dict[str, Any]]:
    """Design section A's `relevance_cache`: a session-scoped, LRU-32
    `(circuito, ventana_i, marked_key) -> ranking` cache wrapping
    `simulate_automatic_minmax_sensitivity`, keyed and invalidated exactly
    as design section A specifies. Disk persistence is restricted to the
    ALL-VANOS key (`marked_key(...) == "__TODOS__"`) -- caching an
    arbitrary marked-vano subset would mean persisting a powerset, which
    design section A rejects as the proposal's mistake.

    Returns a closure `rankear(circuito, ventana_i, marcados) ->
    {'vacio', 'filas', 'n_vanos', 'n_filas', 'mensaje'}`. Zero marked vanos
    returns an explicit empty state (spec's "zero vanos marcados" scenario)
    without a single forward pass -- never a stale or fabricated ranking.
    """
    # `marcados`/`marked_key` are always string FIDs (the widget layer and
    # `capas_mapa_historico` already work in strings); `context_df["FID_VANO"]`
    # is whatever dtype the source CSV produced (int64 in production). Cast
    # once here so `np.isin` below compares like with like -- without this, a
    # real int64 FID_VANO column never matches a stringified marked set and
    # every non-"__TODOS__" ranking silently comes back empty.
    fids = context_df["FID_VANO"].astype(str).to_numpy()
    mask_ventana_para = _construir_evento_mask_cache(context_df, ventanas)
    variable_por_knob = _variable_representativa_por_knob(knobs)
    variables = list(dict.fromkeys(variable_por_knob.values()))
    knobs_por_id = {knob.id: knob for knob in knobs}

    @lru_cache(maxsize=maxsize)
    def _rankear_cacheado(circuito: str, ventana_i: int, clave_marcados: Any) -> tuple[tuple[dict[str, Any], ...], int, int]:
        mask_ventana = mask_ventana_para(circuito, ventana_i)
        if clave_marcados == MARCADOS_TODOS:
            mask = mask_ventana
        else:
            mask = mask_ventana & np.isin(fids, list(clave_marcados))

        if not mask.any():
            return (), 0, 0

        ruta = None
        if clave_marcados == MARCADOS_TODOS:
            ruta = _ruta_cache_todos(circuito, ventana_i, cache_dir=cache_dir)
            en_disco = _cargar_cache_disco(ruta, fingerprint_actual=fingerprint_actual)
            if en_disco is not None:
                return tuple(en_disco), int(mask.sum()), len(set(fids[mask].tolist()))

        tabla_resultado, metadata = simulate_automatic_minmax_sensitivity(
            model=model,
            X_scaled=X_scaled,
            X_raw_model=X_raw_model,
            original_feature_df=original_feature_df,
            feature_names=list(feature_names),
            variables=variables,
            feature_scaler=feature_scaler,
            predict_fn=predict_fn,
            device=device,
            mask=mask,
            label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
            batch_size=batch_size,
        )
        filas = _filas_desde_tabla(tabla_resultado, variable_por_knob, knobs_por_id)

        if ruta is not None:
            _guardar_cache_disco(ruta, filas, fingerprint_actual=fingerprint_actual)

        return tuple(filas), int(metadata["n_filas_base"]), len(set(fids[mask].tolist()))

    def rankear(circuito: str, ventana_i: int, marcados: Iterable[str]) -> dict[str, Any]:
        marcados_set = {str(m) for m in marcados}
        if not marcados_set:
            return {
                "vacio": True,
                "filas": [],
                "n_vanos": 0,
                "n_filas": 0,
                "mensaje": MENSAJE_SIN_MARCADOS,
            }
        mask_ventana = mask_ventana_para(circuito, ventana_i)
        todos_en_ventana = set(fids[mask_ventana].tolist())
        clave = marked_key(marcados_set, todos_en_ventana)
        filas, n_filas, n_vanos = _rankear_cacheado(circuito, ventana_i, clave)
        vacio = len(filas) == 0
        return {
            "vacio": vacio,
            "filas": [dict(fila) for fila in filas],
            "n_vanos": n_vanos,
            "n_filas": n_filas,
            "mensaje": MENSAJE_SIN_FILAS if vacio else None,
        }

    return rankear
