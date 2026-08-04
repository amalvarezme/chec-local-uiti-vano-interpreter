"""RED/GREEN tests for PR2a of notebook 01.5 (Knob catalog).

Covers `chec_local_interpreter.vano_controls`: pure data describing the
control (Knob) each model feature or climate family gets, with NO ipywidgets
dependency -- everything decidable (kind, bounds, step, default, categories)
lives on `Knob` and is tested here without a live kernel.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-risk-simulation`, requirements "Control type follows
    variable kind" and "Climate family sliders propagate to all 12 lags")
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section B)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import LabelEncoder

from chec_local_interpreter.vano_controls import (
    Knob,
    build_knobs,
    categorical_values_for_variable,
    climate_family,
    expand_knob_overrides,
    group_climate_features,
    is_categorical_variable,
    numeric_bounds,
)

# 22 static feature names -- same count as `data/graphs/mgcecdl_feature_order.json`'s
# 22 non-climate entries, kept synthetic here so the test suite does not
# depend on that production data file.
STATIC_VARS = [f"VAR_{i}" for i in range(22)]
CLIMATE_FAMILIES = ("prep", "temp", "wind_gust_spd", "wind_spd")
CLIMATE_VARS = [f"{family}_{lag}" for family in CLIMATE_FAMILIES for lag in range(12)]
ALL_FEATURE_NAMES = STATIC_VARS + CLIMATE_VARS


def _base_original_feature_df() -> pd.DataFrame:
    """A tiny synthetic `Xdf` covering both numeric and categorical static
    variables, plus one row per climate feature."""
    data: dict[str, list] = {}
    for i, var in enumerate(STATIC_VARS):
        if var == "VAR_1":  # categorical via non-numeric dtype
            data[var] = ["A", "B", "A", "C"]
        elif var == "VAR_2":  # categorical via label_encoders membership below
            data[var] = [0, 1, 0, 1]
        else:
            data[var] = [float(i), float(i) + 1.0, float(i) + 2.0, float(i) + 3.0]
    for var in CLIMATE_VARS:
        lag = int(var.rsplit("_", 1)[-1])
        data[var] = [float(lag), float(lag) + 10.0, float(lag) + 20.0, float(lag) + 30.0]
    return pd.DataFrame(data)


# --- 2a.1: is_categorical_variable (encoder + dtype branches) --------------


def test_is_categorical_variable_true_via_label_encoder():
    df = _base_original_feature_df()
    encoder = LabelEncoder().fit(["x", "y"])
    assert is_categorical_variable(
        "VAR_2", original_feature_df=df, label_encoders={"VAR_2": encoder}
    )


def test_is_categorical_variable_true_via_non_numeric_dtype():
    df = _base_original_feature_df()
    assert is_categorical_variable("VAR_1", original_feature_df=df, label_encoders=None)


def test_is_categorical_variable_false_for_numeric_non_encoded_variable():
    df = _base_original_feature_df()
    assert not is_categorical_variable("VAR_0", original_feature_df=df, label_encoders={})


def test_categorical_values_for_variable_uses_encoder_classes():
    df = _base_original_feature_df()
    encoder = LabelEncoder().fit(["baja", "media", "alta"])
    values = categorical_values_for_variable(
        "VAR_2", original_feature_df=df, label_encoders={"VAR_2": encoder}
    )
    assert values == ["alta", "baja", "media"]


def test_categorical_values_for_variable_falls_back_to_dtype_values():
    df = _base_original_feature_df()
    values = categorical_values_for_variable("VAR_1", original_feature_df=df, label_encoders=None)
    assert values == ["A", "B", "C"]


# --- 2a.1: numeric_bounds excludes the -10*max sentinel and NaN ------------


def test_numeric_bounds_excludes_sentinel_and_nan():
    df = pd.DataFrame({"LONGITUD": [1.0, 5.0, 10.0, np.nan, -1000.0]})
    # max_values_imputed["LONGITUD"] = 100 -> sentinel = -10 * 100 = -1000.0,
    # which must be excluded alongside the real NaN.
    bounds = numeric_bounds(
        "LONGITUD", original_feature_df=df, max_values_imputed={"LONGITUD": 100.0}
    )
    assert bounds == (1.0, 10.0)


def test_numeric_bounds_without_sentinel_uses_full_range():
    df = pd.DataFrame({"ALTURA": [2.0, 4.0, 6.0]})
    bounds = numeric_bounds("ALTURA", original_feature_df=df, max_values_imputed=None)
    assert bounds == (2.0, 6.0)


def test_numeric_bounds_returns_none_when_all_values_are_excluded():
    df = pd.DataFrame({"LONGITUD": [np.nan, np.nan]})
    assert numeric_bounds("LONGITUD", original_feature_df=df, max_values_imputed=None) is None


# --- 2a.1: climate_family / group_climate_features fan out to 12/family ----


def test_climate_family_maps_lag_feature_to_family():
    assert climate_family("prep_7") == "prep"
    assert climate_family("wind_gust_spd_3") == "wind_gust_spd"
    assert climate_family("wind_spd_11") == "wind_spd"
    assert climate_family("temp_0") == "temp"


def test_climate_family_returns_none_for_non_climate_feature():
    assert climate_family("LONGITUD") is None
    assert climate_family("wind_spd_extra") is None


def test_group_climate_features_fans_out_to_twelve_per_family():
    groups = group_climate_features(CLIMATE_VARS)
    assert set(groups) == set(CLIMATE_FAMILIES)
    for family in CLIMATE_FAMILIES:
        assert groups[family] == tuple(f"{family}_{lag}" for lag in range(12))


def test_group_climate_features_ignores_static_variables():
    groups = group_climate_features(STATIC_VARS + ["prep_0"])
    assert set(groups) == {"prep"}
    assert groups["prep"] == ("prep_0",)


# --- 2a.2: build_knobs yields 26 knobs (22 static + 4 climate) -------------


def test_build_knobs_yields_twenty_six_knobs():
    df = _base_original_feature_df()
    knobs = build_knobs(
        feature_names=ALL_FEATURE_NAMES,
        original_feature_df=df,
        label_encoders={"VAR_2": LabelEncoder().fit(["off", "on"])},
        max_values_imputed=None,
    )
    assert len(knobs) == 26
    climate_ids = {knob.id for knob in knobs if knob.id.startswith("clima:")}
    assert climate_ids == {f"clima:{family}" for family in CLIMATE_FAMILIES}
    static_ids = {knob.id for knob in knobs if not knob.id.startswith("clima:")}
    assert static_ids == set(STATIC_VARS)


def test_build_knobs_static_numeric_knob_has_bounds_and_slider_kind():
    df = _base_original_feature_df()
    knobs = build_knobs(feature_names=ALL_FEATURE_NAMES, original_feature_df=df)
    by_id = {knob.id: knob for knob in knobs}
    numeric_knob = by_id["VAR_0"]
    assert numeric_knob.kind == "numeric"
    assert numeric_knob.feature_names == ("VAR_0",)
    assert numeric_knob.bounds == (0.0, 3.0)
    assert numeric_knob.step == pytest.approx(0.03)
    assert numeric_knob.default == pytest.approx(1.5)


def test_build_knobs_static_categorical_knob_never_gets_bounds():
    df = _base_original_feature_df()
    knobs = build_knobs(
        feature_names=ALL_FEATURE_NAMES,
        original_feature_df=df,
        label_encoders={"VAR_2": LabelEncoder().fit(["off", "on"])},
    )
    by_id = {knob.id: knob for knob in knobs}
    categorical_knob = by_id["VAR_2"]
    assert categorical_knob.kind == "categorical"
    assert categorical_knob.bounds is None
    assert categorical_knob.categories == ("off", "on")


def test_build_knobs_climate_knob_covers_all_twelve_lag_features():
    df = _base_original_feature_df()
    knobs = build_knobs(feature_names=ALL_FEATURE_NAMES, original_feature_df=df)
    by_id = {knob.id: knob for knob in knobs}
    prep_knob = by_id["clima:prep"]
    assert prep_knob.kind == "numeric"
    assert prep_knob.feature_names == tuple(f"prep_{lag}" for lag in range(12))
    assert prep_knob.bounds == (0.0, 41.0)


def test_build_knobs_constant_variable_gets_constant_kind():
    df = _base_original_feature_df()
    df["VAR_3"] = [5.0, 5.0, 5.0, 5.0]
    knobs = build_knobs(feature_names=ALL_FEATURE_NAMES, original_feature_df=df)
    by_id = {knob.id: knob for knob in knobs}
    constant_knob = by_id["VAR_3"]
    assert constant_knob.kind == "constant"
    assert constant_knob.default == pytest.approx(5.0)


# --- 2a.2: expand_knob_overrides maps 1 family value to 12 feature overrides


def test_expand_knob_overrides_fans_out_climate_family_to_twelve_features():
    df = _base_original_feature_df()
    knobs = build_knobs(feature_names=ALL_FEATURE_NAMES, original_feature_df=df)

    overrides = expand_knob_overrides({"clima:temp": 12.5}, knobs)

    assert len(overrides) == 12
    assert {item["variable"] for item in overrides} == {f"temp_{lag}" for lag in range(12)}
    assert all(item["valor"] == 12.5 for item in overrides)


def test_expand_knob_overrides_maps_static_knob_to_single_feature():
    df = _base_original_feature_df()
    knobs = build_knobs(feature_names=ALL_FEATURE_NAMES, original_feature_df=df)

    overrides = expand_knob_overrides({"VAR_0": 42.0}, knobs)

    assert overrides == [{"variable": "VAR_0", "valor": 42.0}]


def test_expand_knob_overrides_ignores_unknown_knob_id():
    df = _base_original_feature_df()
    knobs = build_knobs(feature_names=ALL_FEATURE_NAMES, original_feature_df=df)

    overrides = expand_knob_overrides({"NO_EXISTE": 1.0}, knobs)

    assert overrides == []


def test_knob_is_frozen_dataclass_instance():
    knob = Knob(
        id="LONGITUD",
        label="LONGITUD",
        kind="numeric",
        feature_names=("LONGITUD",),
        bounds=(0.0, 1.0),
        categories=None,
        default=0.5,
        step=0.01,
    )
    with pytest.raises(Exception):
        knob.id = "otro"  # frozen dataclass must reject mutation
