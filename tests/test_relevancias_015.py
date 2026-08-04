"""RED/GREEN tests for notebook 01.5's `relevancias_015` module (PR4).

Covers the ranked "sensibilidad min-max" panel (row 1 col 2, `IDX['ranking']`
== 6): the slug/fingerprint cache (design section A) and the empty-state
scenario for zero marked vanos (spec's "zero vanos marcados" scenario). This
is a min-max sensitivity sweep, never Kernel SHAP -- see design section A
and decision D5.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-explainability-panel`, "Relevance ranking...")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section A)
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import MinMaxScaler

from chec_local_interpreter.relevancias_015 import (
    MARCADOS_TODOS,
    _cargar_cache_disco,
    _ruta_cache_todos,
    _slug,
    construir_relevance_cache,
    fingerprint,
    marked_key,
)
from chec_local_interpreter.vano_controls import Knob

# --- 4.1 RED (threat-matrix case): path-traversal containment -------------------------


@pytest.mark.parametrize(
    "circuito",
    ["../../etc/passwd", "AGU/../../x", "..", "a/b", "a\\b", "....//....//etc"],
)
def test_slug_rejects_path_separators_and_dot_dot(circuito):
    slug = _slug(circuito)
    assert "/" not in slug
    assert "\\" not in slug
    assert ".." not in slug


@pytest.mark.parametrize(
    "circuito",
    ["../../etc/passwd", "AGU/../../x", "..", "../../../../root", "a/../b"],
)
def test_ruta_cache_todos_never_escapes_cache_dir(tmp_path, circuito):
    base = tmp_path / "relevancias_015"
    ruta = _ruta_cache_todos(circuito, 0, cache_dir=base)
    assert ruta.resolve().is_relative_to(base.resolve())


def test_slug_matches_a_normal_circuit_name():
    assert _slug("AGU23L12") == "AGU23L12"


# --- marked_key -------------------------------------------------------------------------


def test_marked_key_is_todos_sentinel_when_marked_equals_full_window_set():
    assert marked_key(["b", "a"], ["a", "b"]) == MARCADOS_TODOS


def test_marked_key_is_sorted_tuple_for_a_strict_subset():
    assert marked_key(["b"], ["a", "b", "c"]) == ("b",)


# --- fingerprint --------------------------------------------------------------------------


def test_fingerprint_changes_with_model_bytes(tmp_path):
    model_a = tmp_path / "model_a.zip"
    model_b = tmp_path / "model_b.zip"
    model_a.write_bytes(b"contenido-a")
    model_b.write_bytes(b"contenido-b")
    common = dict(geometrias_sha1="sha1x", feature_names=["V1", "V2"], ventana_climatica_horas=12)
    fp_a = fingerprint(model_path=model_a, **common)
    fp_b = fingerprint(model_path=model_b, **common)
    assert fp_a != fp_b
    assert fingerprint(model_path=model_a, **common) == fp_a  # deterministic


def test_fingerprint_changes_with_knob_catalog_version(tmp_path):
    model_path = tmp_path / "model.zip"
    model_path.write_bytes(b"contenido")
    common = dict(
        geometrias_sha1="sha1x",
        model_path=model_path,
        feature_names=["V1", "V2"],
        ventana_climatica_horas=12,
    )
    assert fingerprint(**common, knob_catalog_version=1) != fingerprint(**common, knob_catalog_version=2)


# --- Fixtures shared by the relevance_cache tests ------------------------------------------


def _fake_predict_fn(call_counter):
    def predict_fn(model, X, device, batch_size=1024):
        call_counter[0] += 1
        x = np.asarray(X)[:, 0]
        probs = np.zeros((len(x), 3), dtype=float)
        probs[:, 0] = 1.0 - x
        probs[:, 2] = x
        return {"fused_probs": probs, "predicted_classes": probs.argmax(axis=1)}

    return predict_fn


def _build_context(tmp_path, call_counter, fid_vano=("v1", "v2", "v3")):
    feature_names = ["CNT_TRF", "CNT_VN"]
    X_raw = np.array([[0.0, 1.0], [10.0, 2.0], [5.0, 3.0]], dtype=np.float32)
    scaler = MinMaxScaler().fit(X_raw)
    X_scaled = scaler.transform(X_raw).astype(np.float32)
    original_df = pd.DataFrame({"CNT_TRF": [0.0, 10.0, 5.0], "CNT_VN": [1.0, 2.0, 3.0]})
    # `context_df` is the RAW event-row table (row-aligned with X/X_scaled) -- a different
    # row space than `ventanas_015.TABLA`'s per-(vano, ventana) aggregation. This mirrors
    # `procesar_dataset_completo`'s `df_original_copy`, which 01.5's SEAM cell keeps
    # row-aligned with `X` on purpose (see cell 4's own assert).
    context_df = pd.DataFrame(
        {
            "CIRCUITO": ["C1", "C1", "C1"],
            "FID_VANO": list(fid_vano),
            "FECHA": pd.to_datetime(["2024-01-05", "2024-01-10", "2024-01-15"]),
        }
    )
    ventanas = [{"i": 0, "desde": pd.Timestamp("2024-01-01"), "hasta_excl": pd.Timestamp("2024-02-01")}]
    knobs = [
        Knob(id="CNT_TRF", label="CNT_TRF", kind="numeric", feature_names=("CNT_TRF",),
             bounds=(0.0, 10.0), categories=None, default=5.0, step=0.1),
        Knob(id="CNT_VN", label="CNT_VN", kind="numeric", feature_names=("CNT_VN",),
             bounds=(1.0, 3.0), categories=None, default=2.0, step=0.1),
    ]
    model_path = tmp_path / "model.zip"
    model_path.write_bytes(b"contenido-modelo")
    fp = fingerprint(
        geometrias_sha1="sha1x",
        model_path=model_path,
        feature_names=feature_names,
        ventana_climatica_horas=12,
    )
    cache = construir_relevance_cache(
        model=object(),
        X_scaled=X_scaled,
        X_raw_model=X_raw,
        original_feature_df=original_df,
        feature_names=feature_names,
        knobs=knobs,
        feature_scaler=scaler,
        predict_fn=_fake_predict_fn(call_counter),
        device="cpu",
        context_df=context_df,
        ventanas=ventanas,
        fingerprint_actual=fp,
        cache_dir=tmp_path / "cache",
        batch_size=1024,
    )
    return cache, fp, tmp_path / "cache"


# --- 4.5 RED/GREEN: zero marked vanos -> explicit empty state -----------------------------


def test_zero_marked_vanos_returns_explicit_empty_state_without_calling_the_model(tmp_path):
    call_counter = [0]
    cache, _fp, _cache_dir = _build_context(tmp_path, call_counter)

    resultado = cache("C1", 0, [])

    assert resultado["vacio"] is True
    assert resultado["filas"] == []
    assert resultado["mensaje"]
    assert call_counter[0] == 0


# --- 4.3/4.4 GREEN: disk cache (all-vanos key only) + fingerprint mismatch discards it -----


def test_all_vanos_key_is_the_only_one_persisted_to_disk(tmp_path):
    call_counter = [0]
    cache, fp, cache_dir = _build_context(tmp_path, call_counter)

    resultado_subset = cache("C1", 0, ["v1"])
    assert resultado_subset["vacio"] is False
    assert not (cache_dir / "C1" / "0.json").exists()  # subset key never hits disk

    resultado_todos = cache("C1", 0, ["v1", "v2", "v3"])
    assert resultado_todos["vacio"] is False
    ruta = cache_dir / "C1" / "0.json"
    assert ruta.exists()
    payload = json.loads(ruta.read_text(encoding="utf-8"))
    assert payload["fingerprint"] == fp
    assert payload["filas"]


def test_fingerprint_mismatch_discards_a_disk_cache_entry(tmp_path):
    call_counter = [0]
    cache, fp, cache_dir = _build_context(tmp_path, call_counter)

    cache("C1", 0, ["v1", "v2", "v3"])  # populates the disk cache for the __TODOS__ key
    calls_after_first_write = call_counter[0]
    assert calls_after_first_write > 0

    ruta = cache_dir / "C1" / "0.json"
    stale_payload = json.loads(ruta.read_text(encoding="utf-8"))
    stale_payload["fingerprint"] = "un-fingerprint-viejo-que-no-coincide"
    ruta.write_text(json.dumps(stale_payload), encoding="utf-8")

    # A fresh cache (new in-process LRU, same fingerprint_actual as before) must not trust
    # the tampered file and must recompute instead of serving the stale ranking.
    cache_fresco, fp_fresco, _ = _build_context(tmp_path, call_counter)
    assert fp_fresco == fp
    resultado = cache_fresco("C1", 0, ["v1", "v2", "v3"])

    assert call_counter[0] > calls_after_first_write  # recomputed, stale entry discarded
    payload_final = json.loads(ruta.read_text(encoding="utf-8"))
    assert payload_final["fingerprint"] == fp  # overwritten with the current fingerprint
    assert resultado["vacio"] is False


def test_cargar_cache_disco_returns_none_for_missing_or_mismatched_fingerprint(tmp_path):
    ruta = tmp_path / "x" / "0.json"
    assert _cargar_cache_disco(ruta, fingerprint_actual="abc") is None  # missing file

    ruta.parent.mkdir(parents=True)
    ruta.write_text(json.dumps({"fingerprint": "otro", "filas": [{"a": 1}]}), encoding="utf-8")
    assert _cargar_cache_disco(ruta, fingerprint_actual="abc") is None  # mismatch

    ruta.write_text(json.dumps({"fingerprint": "abc", "filas": [{"a": 1}]}), encoding="utf-8")
    assert _cargar_cache_disco(ruta, fingerprint_actual="abc") == [{"a": 1}]


def test_session_relevance_cache_memoizes_the_same_marked_key(tmp_path):
    call_counter = [0]
    cache, _fp, _cache_dir = _build_context(tmp_path, call_counter)

    cache("C1", 0, ["v1"])
    calls_first = call_counter[0]
    cache("C1", 0, ["v1"])  # same (circuito, ventana_i, marked_key) -> served from the LRU
    assert call_counter[0] == calls_first


def test_ranking_is_labelled_by_knob_not_by_raw_feature(tmp_path):
    call_counter = [0]
    cache, _fp, _cache_dir = _build_context(tmp_path, call_counter)

    resultado = cache("C1", 0, ["v1", "v2", "v3"])
    knob_ids = {fila["knob_id"] for fila in resultado["filas"]}
    assert knob_ids <= {"CNT_TRF", "CNT_VN"}
    assert all("shap" not in fila["label"].lower() for fila in resultado["filas"])


def test_int64_fid_vano_column_matches_string_marcados(tmp_path):
    """Regression: production `context_df['FID_VANO']` is int64, not str.
    A marked-vano list of strings (as the widget layer /
    `capas_mapa_historico` always produce) must still match, not silently
    mask out every row."""
    call_counter = [0]
    cache, _fp, _cache_dir = _build_context(
        tmp_path, call_counter, fid_vano=(20130434, 20130436, 20130437)
    )

    resultado = cache("C1", 0, ["20130434"])  # a single str-typed marked FID

    assert resultado["vacio"] is False
    assert resultado["n_vanos"] == 1
    assert resultado["n_filas"] == 1
