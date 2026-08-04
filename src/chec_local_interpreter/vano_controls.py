"""Knob catalog for notebook 01.5's risk simulator (PR2a).

A `Knob` is a pure-data control spec mapping ONE user-facing control to
1..N model feature indices. The 70 MGCECDL features collapse to 26 knobs:
22 static features get one knob each, and the 4 climate families
(`prep_`, `temp_`, `wind_gust_spd_`, `wind_spd_`, each with 12 twelve-hour
lags) get one family-level knob whose value fans out to all 12 lag
features via `expand_knob_overrides`.

This module MUST NOT import `ipywidgets` -- everything decidable (kind,
bounds, step, default, categories) is data on `Knob`, unit-tested here
without a live kernel. `vano_widgets.widget_for_knob` turns a `Knob` into
an actual widget and is the only place `ipywidgets` is imported.

`vano_controls` knows about features and knobs, never about a specific
model -- this keeps the MIL swap of D1 (see design section D) independent
of the simulator UI.

See:
  - spec: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/spec`
    (domain `vano-risk-simulation`)
  - design: `sdd/notebook-15-trayectorias-vano-explicabilidad-simulador/design`
    (section B)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

CLIMATE_FAMILY_PREFIXES: tuple[str, ...] = (
    "prep_",
    "temp_",
    "wind_gust_spd_",
    "wind_spd_",
)

_CLIMATE_FAMILY_LABELS: dict[str, str] = {
    "prep": "Precipitacion (12 lags)",
    "temp": "Temperatura (12 lags)",
    "wind_gust_spd": "Rafaga de viento (12 lags)",
    "wind_spd": "Viento (12 lags)",
}


@dataclass(frozen=True)
class Knob:
    """One user-facing control, mapped to 1..N model feature indices."""

    id: str  # e.g. "LONGITUD" or "clima:prep"
    label: str
    kind: str  # "numeric" | "categorical" | "constant"
    feature_names: tuple[str, ...]  # 1 for a static variable, 12 for a climate family
    bounds: tuple[float, float] | None
    categories: tuple[str, ...] | None
    default: float | str | None
    step: float | None


def is_categorical_variable(
    variable: str,
    *,
    original_feature_df: pd.DataFrame,
    label_encoders: Mapping[str, Any] | None = None,
) -> bool:
    """A variable is categorical if it has a `label_encoders` entry, or if
    its dtype in `original_feature_df` is not numeric."""
    label_encoders = label_encoders or {}
    if variable in label_encoders:
        return True
    return not pd.api.types.is_numeric_dtype(original_feature_df[variable])


def categorical_values_for_variable(
    variable: str,
    *,
    original_feature_df: pd.DataFrame,
    label_encoders: Mapping[str, Any] | None = None,
    max_values: int | None = None,
) -> list[str]:
    """The categories offered for a categorical variable: the encoder's
    known classes when one exists, otherwise the distinct raw values seen
    in `original_feature_df`."""
    label_encoders = label_encoders or {}
    if variable in label_encoders:
        values = [str(value) for value in label_encoders[variable].classes_]
    else:
        values = sorted(original_feature_df[variable].dropna().astype(str).unique().tolist())
    values = values or ["no aplica"]
    return values if max_values is None else values[:max_values]


def _numeric_series_for_variable(
    variable: str,
    *,
    original_feature_df: pd.DataFrame,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> pd.Series:
    """Clean numeric raw-scale values for `variable`: true NaN dropped, and
    the `-10 * max_values_imputed[var]` NaN sentinel excluded belt-and-braces
    (see `simulator._coerce_original_value_for_model`)."""
    max_values_imputed = max_values_imputed or {}
    series = pd.to_numeric(original_feature_df[variable], errors="coerce").dropna()
    max_val = float(max_values_imputed.get(variable, 0.0) or 0.0)
    if max_val > 0:
        sentinel = -10.0 * max_val
        series = series[series > sentinel]
    return series


def numeric_bounds(
    variable: str,
    *,
    original_feature_df: pd.DataFrame,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> tuple[float, float] | None:
    """`(min, max)` over the full dataset's raw-scale values, excluding the
    NaN sentinel. `None` when no usable value remains."""
    series = _numeric_series_for_variable(
        variable, original_feature_df=original_feature_df, max_values_imputed=max_values_imputed
    )
    if series.empty:
        return None
    return float(series.min()), float(series.max())


def climate_family(feature_name: str) -> str | None:
    """`"prep_7"` -> `"prep"`; `None` when `feature_name` is not a
    twelve-hour climate lag feature."""
    for prefix in CLIMATE_FAMILY_PREFIXES:
        if not feature_name.startswith(prefix):
            continue
        suffix = feature_name[len(prefix) :]
        if suffix.isdigit():
            return prefix.rstrip("_")
    return None


def _lag_index(feature_name: str) -> int:
    return int(feature_name.rsplit("_", 1)[-1])


def group_climate_features(feature_names: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """Group `feature_names` by climate family, each family's features
    sorted by lag index. Non-climate feature names are ignored."""
    groups: dict[str, list[str]] = {}
    for name in feature_names:
        family = climate_family(name)
        if family is None:
            continue
        groups.setdefault(family, []).append(name)
    return {family: tuple(sorted(names, key=_lag_index)) for family, names in groups.items()}


def _numeric_series_for_family(
    feature_names: Sequence[str],
    *,
    original_feature_df: pd.DataFrame,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> pd.Series:
    parts = [
        _numeric_series_for_variable(
            name, original_feature_df=original_feature_df, max_values_imputed=max_values_imputed
        )
        for name in feature_names
    ]
    if not parts:
        return pd.Series([], dtype=float)
    return pd.concat(parts, ignore_index=True)


def _numeric_knob(
    *,
    knob_id: str,
    label: str,
    feature_names: tuple[str, ...],
    series: pd.Series,
) -> Knob:
    if series.empty:
        return Knob(
            id=knob_id,
            label=label,
            kind="constant",
            feature_names=feature_names,
            bounds=None,
            categories=None,
            default=None,
            step=None,
        )

    lo = float(series.min())
    hi = float(series.max())
    if np.isclose(lo, hi):
        return Knob(
            id=knob_id,
            label=label,
            kind="constant",
            feature_names=feature_names,
            bounds=(lo, hi),
            categories=None,
            default=lo,
            step=None,
        )

    default = float(series.median())
    step = max((hi - lo) / 100.0, 1e-6)
    return Knob(
        id=knob_id,
        label=label,
        kind="numeric",
        feature_names=feature_names,
        bounds=(lo, hi),
        categories=None,
        default=default,
        step=step,
    )


def _build_static_knob(
    variable: str,
    *,
    original_feature_df: pd.DataFrame,
    label_encoders: Mapping[str, Any],
    max_values_imputed: Mapping[str, Any] | None,
) -> Knob:
    if is_categorical_variable(
        variable, original_feature_df=original_feature_df, label_encoders=label_encoders
    ):
        categories = tuple(
            categorical_values_for_variable(
                variable, original_feature_df=original_feature_df, label_encoders=label_encoders
            )
        )
        default = categories[0] if categories else None
        # A single category (including the "no aplica" fallback) has
        # nothing to vary -- treat it as a disabled constant, not a
        # one-option dropdown.
        kind = "constant" if len(categories) <= 1 else "categorical"
        return Knob(
            id=variable,
            label=variable,
            kind=kind,
            feature_names=(variable,),
            bounds=None,
            categories=categories or None,
            default=default,
            step=None,
        )

    series = _numeric_series_for_variable(
        variable, original_feature_df=original_feature_df, max_values_imputed=max_values_imputed
    )
    return _numeric_knob(
        knob_id=variable, label=variable, feature_names=(variable,), series=series
    )


def _build_climate_knob(
    family: str,
    feature_names: tuple[str, ...],
    *,
    original_feature_df: pd.DataFrame,
    max_values_imputed: Mapping[str, Any] | None,
) -> Knob:
    series = _numeric_series_for_family(
        feature_names,
        original_feature_df=original_feature_df,
        max_values_imputed=max_values_imputed,
    )
    label = _CLIMATE_FAMILY_LABELS.get(family, family)
    return _numeric_knob(
        knob_id=f"clima:{family}", label=label, feature_names=feature_names, series=series
    )


def build_knobs(
    *,
    feature_names: Sequence[str],
    original_feature_df: pd.DataFrame,
    label_encoders: Mapping[str, Any] | None = None,
    max_values_imputed: Mapping[str, Any] | None = None,
) -> list[Knob]:
    """The full knob catalog: one knob per static feature, plus one
    family-level knob per climate family present in `feature_names`."""
    label_encoders = label_encoders or {}
    climate_groups = group_climate_features(feature_names)
    climate_feature_set = {name for names in climate_groups.values() for name in names}

    knobs: list[Knob] = [
        _build_static_knob(
            variable,
            original_feature_df=original_feature_df,
            label_encoders=label_encoders,
            max_values_imputed=max_values_imputed,
        )
        for variable in feature_names
        if variable not in climate_feature_set
    ]
    knobs.extend(
        _build_climate_knob(
            family,
            names,
            original_feature_df=original_feature_df,
            max_values_imputed=max_values_imputed,
        )
        for family, names in climate_groups.items()
    )
    return knobs


def expand_knob_overrides(
    knob_values: Mapping[str, Any], knobs: Sequence[Knob]
) -> list[dict[str, Any]]:
    """Turn `{knob_id: value}` into the flat `[{"variable", "valor"}]` list
    `simulator.simulate_explicit_overrides` expects -- one entry per feature
    a knob controls (1 for a static knob, 12 for a climate family knob).
    Unknown knob ids are silently ignored."""
    by_id = {knob.id: knob for knob in knobs}
    overrides: list[dict[str, Any]] = []
    for knob_id, value in knob_values.items():
        knob = by_id.get(knob_id)
        if knob is None:
            continue
        overrides.extend({"variable": feature_name, "valor": value} for feature_name in knob.feature_names)
    return overrides
