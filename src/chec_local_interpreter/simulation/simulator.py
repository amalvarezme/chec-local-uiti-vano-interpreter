from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


PRIORITIZED_VARIABLES_FILENAME = "variables_a_priorizar.xlsx"
SIMULATOR_RESULTS_FILENAME = "simulador_clasificacion_resultados.xlsx"
AUTO_MINMAX_SIMULATOR_RESULTS_FILENAME = "simulador_automatico_minmax_resultados.xlsx"


def prioritized_variables_path(report_dir: str | Path) -> Path:
    return Path(report_dir) / PRIORITIZED_VARIABLES_FILENAME


def simulator_results_path(report_dir: str | Path) -> Path:
    return Path(report_dir) / SIMULATOR_RESULTS_FILENAME


def auto_minmax_simulator_results_path(report_dir: str | Path) -> Path:
    return Path(report_dir) / AUTO_MINMAX_SIMULATOR_RESULTS_FILENAME


def simulator_plots_dir(report_dir: str | Path) -> Path:
    return Path(report_dir) / "simulador"


def save_prioritized_variables_table(
    analysis: dict[str, Any] | None,
    path: str | Path,
    *,
    circuito: str | None = None,
    periodo_inicio: Any = None,
    periodo_fin: Any = None,
) -> Path:
    rows = []
    if isinstance(analysis, dict):
        rows = analysis.get("variables_a_priorizar", []) or []
    if not isinstance(rows, list) or not rows:
        raise ValueError("La tabla de variables a priorizar está vacía; no se guarda archivo.")

    df = pd.DataFrame([item for item in rows if isinstance(item, dict)])
    if df.empty:
        raise ValueError("La tabla de variables a priorizar no contiene filas válidas.")
    if "variable" not in df.columns:
        raise ValueError("La tabla de variables a priorizar no contiene la columna 'variable'.")

    df.insert(0, "circuito", str(circuito or ""))
    df.insert(1, "periodo_inicio", "" if periodo_inicio is None else str(periodo_inicio))
    df.insert(2, "periodo_fin", "" if periodo_fin is None else str(periodo_fin))

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(target, index=False)
    return target


def read_prioritized_variables_table(path: str | Path) -> tuple[pd.DataFrame, list[str]]:
    source = Path(path)
    if not source.exists():
        return pd.DataFrame(columns=["variable"]), [f"No existe la tabla de variables priorizadas: {source}"]
    try:
        if source.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(source)
        else:
            df = pd.read_csv(source)
    except Exception as exc:  # pragma: no cover - depends on local file engines
        return pd.DataFrame(columns=["variable"]), [f"No se pudo leer la tabla de variables priorizadas: {exc}"]
    if "variable" not in df.columns:
        return pd.DataFrame(columns=["variable"]), ["La tabla de variables priorizadas no tiene columna 'variable'."]
    df = df.copy()
    df["variable"] = df["variable"].fillna("").astype(str).str.strip()
    df = df[df["variable"] != ""].reset_index(drop=True)
    return df, []


def validate_prioritized_variables(
    prioritized_df: pd.DataFrame,
    feature_names: list[str],
) -> tuple[list[str], list[str]]:
    feature_set = {str(item) for item in feature_names}
    valid: list[str] = []
    warnings_out: list[str] = []
    for variable in prioritized_df.get("variable", []):
        text = str(variable).strip()
        if not text:
            continue
        if text in feature_set:
            if text not in valid:
                valid.append(text)
        else:
            warnings_out.append(f"Variable priorizada omitida porque no está en feature_names: {text}")
    return valid, warnings_out


def risk_class_labels(n_classes: int) -> list[str]:
    """Return human-readable ordinal risk labels for classifier outputs."""
    if n_classes == 4:
        return [
            "Riesgo bajo (Q1)",
            "Riesgo medio-bajo (Q2)",
            "Riesgo medio-alto (Q3)",
            "Riesgo alto (Q4)",
        ]
    if n_classes == 3:
        return ["Riesgo bajo", "Riesgo medio", "Riesgo alto"]
    if n_classes == 2:
        return ["Riesgo bajo", "Riesgo alto"]
    return [f"Riesgo ordinal {idx}" for idx in range(n_classes)]


def prioritized_circuit_default(prioritized_df: pd.DataFrame, context_df: pd.DataFrame) -> str:
    """Pick the first prioritized circuit that exists in the context data."""
    if "circuito" not in prioritized_df.columns or "CIRCUITO" not in context_df.columns:
        return "Todos"
    candidates = prioritized_df["circuito"].dropna().astype(str).str.strip()
    candidates = candidates[candidates.ne("")]
    if candidates.empty:
        return "Todos"
    available = set(context_df["CIRCUITO"].dropna().astype(str))
    for candidate in candidates:
        if candidate in available:
            return candidate
    return "Todos"


def variable_options_for_mode(
    mode: str,
    prioritized_variables: list[str],
    available_model_variables: list[str],
) -> list[str]:
    """Return variables exposed by the selected simulator mode."""
    if mode == "Variables priorizadas" and prioritized_variables:
        return prioritized_variables
    return available_model_variables


def sorted_text_values(series: pd.Series) -> list[str]:
    """Return sorted non-null string values from a Series."""
    return sorted(series.dropna().astype(str).unique().tolist())


def context_dates(context_df: pd.DataFrame, *, date_col: str = "FECHA") -> pd.Series:
    """Parse context dates while preserving the original index."""
    if date_col not in context_df.columns:
        return pd.Series(pd.NaT, index=context_df.index)
    return pd.to_datetime(context_df[date_col], errors="coerce")


def context_filter_mask(
    context_df: pd.DataFrame,
    *,
    circuito: Any = "Todos",
    fid_vano: Any = "Todos",
    fecha_inicio: Any = None,
    fecha_fin: Any = None,
    parsed_dates: pd.Series | None = None,
) -> np.ndarray:
    """Build a boolean mask for circuit/span/date simulator filters."""
    mask = pd.Series(True, index=context_df.index)
    if circuito not in (None, "", "Todos") and "CIRCUITO" in context_df.columns:
        mask &= context_df["CIRCUITO"].astype(str).eq(str(circuito))
    if fid_vano not in (None, "", "Todos") and "FID_VANO" in context_df.columns:
        mask &= context_df["FID_VANO"].astype(str).eq(str(fid_vano))
    dates = parsed_dates if parsed_dates is not None else context_dates(context_df)
    valid_dates = dates.dropna()
    if not valid_dates.empty:
        if fecha_inicio is not None:
            mask &= dates.ge(pd.Timestamp(fecha_inicio))
        if fecha_fin is not None:
            mask &= dates.le(pd.Timestamp(fecha_fin))
    return mask.to_numpy(dtype=bool)


def circuit_options(context_df: pd.DataFrame) -> list[str]:
    """Return simulator circuit filter options."""
    if "CIRCUITO" not in context_df.columns:
        return ["Todos"]
    return ["Todos"] + sorted_text_values(context_df["CIRCUITO"])


def vano_options_for_circuit(context_df: pd.DataFrame, circuito: Any = "Todos") -> list[str]:
    """Return simulator span filter options for a circuit."""
    if "FID_VANO" not in context_df.columns:
        return ["Todos"]
    if circuito not in (None, "", "Todos") and "CIRCUITO" in context_df.columns:
        mask = context_df["CIRCUITO"].astype(str).eq(str(circuito))
        values = sorted_text_values(context_df.loc[mask, "FID_VANO"])
    else:
        values = sorted_text_values(context_df["FID_VANO"])
    return ["Todos"] + values


def is_categorical_variable(variable: str, Xdf: pd.DataFrame, label_encoders: dict[str, Any] | None = None) -> bool:
    """Return whether a simulator variable should be treated as categorical."""
    label_encoders = label_encoders or {}
    if variable in label_encoders:
        return True
    return not pd.api.types.is_numeric_dtype(Xdf[variable])


def categorical_values_for_variable(
    variable: str,
    Xdf: pd.DataFrame,
    *,
    label_encoders: dict[str, Any] | None = None,
    max_values: int | None = None,
) -> list[str]:
    """Return categorical values available for simulator evaluation."""
    label_encoders = label_encoders or {}
    if variable in label_encoders:
        values = [str(value) for value in label_encoders[variable].classes_]
    else:
        values = sorted_text_values(Xdf[variable])
    values = values or ["no aplica"]
    return values if max_values is None else values[:max_values]


def values_grid_for_variable(
    variable: str,
    Xdf: pd.DataFrame,
    *,
    selected_value: Any = None,
    label_encoders: dict[str, Any] | None = None,
    max_values: int = 18,
) -> list[Any]:
    """Return original values to evaluate for one simulator variable."""
    if is_categorical_variable(variable, Xdf, label_encoders):
        return categorical_values_for_variable(variable, Xdf, label_encoders=label_encoders)
    values = default_simulation_values(Xdf[variable], max_values=max_values)
    if selected_value not in (None, "") and selected_value not in values:
        values.append(selected_value)
    return values


def _coerce_original_value_for_model(
    variable: str,
    value: Any,
    *,
    label_encoders: dict[str, Any] | None = None,
    max_values_imputed: dict[str, Any] | None = None,
) -> float:
    label_encoders = label_encoders or {}
    max_values_imputed = max_values_imputed or {}

    if variable in label_encoders:
        encoder = label_encoders[variable]
        text = "no aplica" if pd.isna(value) else str(value)
        if text not in set(map(str, encoder.classes_)):
            raise ValueError(f"Categoría no vista por el encoder de {variable}: {text}")
        return float(encoder.transform([text])[0])

    parsed_date = pd.to_datetime(value, errors="coerce")
    if not pd.isna(parsed_date) and not isinstance(value, (int, float, np.integer, np.floating)):
        return float(parsed_date.value // 10**9)

    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        max_val = float(max_values_imputed.get(variable, 0.0) or 0.0)
        return float(-10.0 * max_val)
    return float(numeric)


def transform_single_feature_value(
    variable: str,
    value: Any,
    *,
    baseline_raw_row: np.ndarray,
    feature_names: list[str],
    feature_scaler: Any,
    label_encoders: dict[str, Any] | None = None,
    max_values_imputed: dict[str, Any] | None = None,
) -> float:
    if variable not in feature_names:
        raise KeyError(f"{variable} no está en feature_names.")
    raw_row = np.asarray(baseline_raw_row, dtype=np.float32).reshape(1, -1).copy()
    idx = feature_names.index(variable)
    raw_row[0, idx] = _coerce_original_value_for_model(
        variable,
        value,
        label_encoders=label_encoders,
        max_values_imputed=max_values_imputed,
    )
    scaled = feature_scaler.transform(raw_row).astype(np.float32)
    return float(scaled[0, idx])


def default_simulation_values(series: pd.Series, *, max_values: int = 12) -> list[Any]:
    clean = series.dropna()
    if clean.empty:
        return []
    if pd.api.types.is_numeric_dtype(clean):
        values = pd.to_numeric(clean, errors="coerce").dropna()
        if values.empty:
            return []
        if values.nunique() <= max_values:
            return sorted(values.unique().tolist())
        quantiles = np.linspace(0.05, 0.95, max_values)
        return sorted(pd.Series(values.quantile(quantiles).unique()).dropna().tolist())
    counts = clean.astype(str).value_counts()
    return counts.head(max_values).index.tolist()



def predict_probabilities(
    model: Any,
    X: np.ndarray,
    *,
    predict_fn: Callable[..., dict[str, Any]],
    device: str,
    batch_size: int = 1024,
) -> tuple[np.ndarray, np.ndarray]:
    outputs = predict_fn(model, np.asarray(X, dtype=np.float32), device=device, batch_size=batch_size)
    probs = np.asarray(outputs["fused_probs"], dtype=np.float64)
    preds = np.asarray(outputs["predicted_classes"], dtype=int)
    return probs, preds


def simulate_feature_values(
    *,
    model: Any,
    X_scaled: np.ndarray,
    X_raw_model: np.ndarray,
    original_feature_df: pd.DataFrame,
    feature_names: list[str],
    variable: str,
    values_original: list[Any],
    feature_scaler: Any,
    predict_fn: Callable[..., dict[str, Any]],
    device: str,
    class_index: int,
    mask: np.ndarray | None = None,
    label_encoders: dict[str, Any] | None = None,
    max_values_imputed: dict[str, Any] | None = None,
    batch_size: int = 1024,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if variable not in feature_names:
        raise KeyError(f"{variable} no está en feature_names.")
    if variable not in original_feature_df.columns:
        raise KeyError(f"{variable} no está disponible en valores originales.")
    if not values_original:
        raise ValueError(f"No hay valores originales simulables para {variable}.")

    X_scaled = np.asarray(X_scaled, dtype=np.float32)
    X_raw_model = np.asarray(X_raw_model, dtype=np.float32)
    if mask is None:
        mask = np.ones(X_scaled.shape[0], dtype=bool)
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        raise ValueError("El subconjunto base está vacío con los filtros seleccionados.")

    X_base = X_scaled[mask].copy()
    X_raw_base = X_raw_model[mask].copy()
    baseline_probs, baseline_preds = predict_probabilities(
        model,
        X_base,
        predict_fn=predict_fn,
        device=device,
        batch_size=batch_size,
    )
    if class_index < 0 or class_index >= baseline_probs.shape[1]:
        raise ValueError(f"Clase objetivo fuera de rango: {class_index}")

    baseline_prob = float(baseline_probs[:, class_index].mean())
    baseline_majority = int(pd.Series(baseline_preds).mode().iloc[0])
    feature_idx = feature_names.index(variable)
    rows: list[dict[str, Any]] = []
    warnings_out: list[str] = []

    for value in values_original:
        try:
            transformed_value = transform_single_feature_value(
                variable,
                value,
                baseline_raw_row=X_raw_base[0],
                feature_names=feature_names,
                feature_scaler=feature_scaler,
                label_encoders=label_encoders,
                max_values_imputed=max_values_imputed,
            )
        except Exception as exc:
            warnings_out.append(f"{variable}={value}: {exc}")
            continue
        X_sim = X_base.copy()
        X_sim[:, feature_idx] = transformed_value
        sim_probs, sim_preds = predict_probabilities(
            model,
            X_sim,
            predict_fn=predict_fn,
            device=device,
            batch_size=batch_size,
        )
        sim_prob = float(sim_probs[:, class_index].mean())
        delta_abs = sim_prob - baseline_prob
        delta_pct = np.nan if abs(baseline_prob) < 1e-12 else (delta_abs / baseline_prob) * 100.0
        rows.append(
            {
                "variable": variable,
                "valor_original": value,
                "clase_objetivo": int(class_index),
                "n_filas_base": int(mask.sum()),
                "probabilidad_baseline": baseline_prob,
                "probabilidad_simulada": sim_prob,
                "cambio_absoluto": delta_abs,
                "cambio_porcentual": delta_pct,
                "clase_mayoritaria_baseline": baseline_majority,
                "clase_mayoritaria_simulada": int(pd.Series(sim_preds).mode().iloc[0]),
            }
        )

    result = pd.DataFrame(rows)
    metadata = {
        "baseline_probabilidad_clase_objetivo": baseline_prob,
        "baseline_clase_mayoritaria": baseline_majority,
        "warnings": warnings_out,
    }
    return result, metadata


def simulate_feature_class_transitions(
    *,
    model: Any,
    X_scaled: np.ndarray,
    X_raw_model: np.ndarray,
    original_feature_df: pd.DataFrame,
    feature_names: list[str],
    variable: str,
    values_original: list[Any],
    feature_scaler: Any,
    predict_fn: Callable[..., dict[str, Any]],
    device: str,
    mask: np.ndarray,
    label_encoders: dict[str, Any] | None = None,
    max_values_imputed: dict[str, Any] | None = None,
    batch_size: int = 1024,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Simulate one feature and report class transitions over a base subset."""
    if variable not in feature_names:
        raise KeyError(f"{variable} no está en feature_names.")
    if variable not in original_feature_df.columns:
        raise KeyError(f"{variable} no está disponible en valores originales.")
    if not values_original:
        raise ValueError(f"No hay valores originales simulables para {variable}.")

    X_scaled = np.asarray(X_scaled, dtype=np.float32)
    X_raw_model = np.asarray(X_raw_model, dtype=np.float32)
    mask = np.asarray(mask, dtype=bool)
    if mask.shape[0] != X_scaled.shape[0]:
        raise ValueError("La máscara no tiene la misma longitud que X_scaled.")
    if not mask.any():
        raise ValueError("El subconjunto base está vacío con los filtros seleccionados.")

    X_base = X_scaled[mask].copy()
    X_raw_base = X_raw_model[mask].copy()
    baseline_probs, baseline_preds = predict_probabilities(
        model,
        X_base,
        predict_fn=predict_fn,
        device=device,
        batch_size=batch_size,
    )
    n_rows = int(mask.sum())
    baseline_classes = baseline_preds.astype(int)
    baseline_majority = int(pd.Series(baseline_classes).mode().iloc[0])
    baseline_confidences = baseline_probs[np.arange(n_rows), baseline_classes]
    baseline_distribution = (
        pd.Series(baseline_classes).value_counts(normalize=True).sort_index().to_dict()
    )
    feature_idx = feature_names.index(variable)
    rows: list[dict[str, Any]] = []
    warnings_out: list[str] = []

    for value in values_original:
        try:
            transformed_value = transform_single_feature_value(
                variable,
                value,
                baseline_raw_row=X_raw_base[0],
                feature_names=feature_names,
                feature_scaler=feature_scaler,
                label_encoders=label_encoders,
                max_values_imputed=max_values_imputed,
            )
        except Exception as exc:
            warnings_out.append(f"{variable}={value}: {exc}")
            continue
        X_sim = X_base.copy()
        X_sim[:, feature_idx] = transformed_value
        sim_probs, sim_preds = predict_probabilities(
            model,
            X_sim,
            predict_fn=predict_fn,
            device=device,
            batch_size=batch_size,
        )
        sim_classes = sim_preds.astype(int)
        delta_classes = sim_classes - baseline_classes
        pct_up = float(np.mean(delta_classes > 0))
        pct_down = float(np.mean(delta_classes < 0))
        pct_equal = float(np.mean(delta_classes == 0))
        if pct_up > pct_down:
            direction = "sube"
        elif pct_down > pct_up:
            direction = "baja"
        else:
            direction = "igual"
        probability_up = float(
            np.mean([
                sim_probs[i, baseline_class + 1 :].sum()
                for i, baseline_class in enumerate(baseline_classes)
            ])
        )
        probability_down = float(
            np.mean([
                sim_probs[i, :baseline_class].sum()
                for i, baseline_class in enumerate(baseline_classes)
            ])
        )
        sim_confidences = sim_probs[np.arange(n_rows), sim_classes]
        sim_majority = int(pd.Series(sim_classes).mode().iloc[0])
        rows.append(
            {
                "variable": variable,
                "valor_original": value,
                "n_filas_base": n_rows,
                "clase_mayoritaria_baseline": baseline_majority,
                "clase_mayoritaria_simulada": sim_majority,
                "direccion_cambio": direction,
                "pct_sube_clase": pct_up,
                "pct_baja_clase": pct_down,
                "pct_igual_clase": pct_equal,
                "cambio_promedio_clase": float(np.mean(delta_classes)),
                "probabilidad_subir": probability_up,
                "probabilidad_bajar": probability_down,
                "confianza_baseline_promedio": float(np.mean(baseline_confidences)),
                "confianza_simulada_promedio": float(np.mean(sim_confidences)),
            }
        )
        for class_idx in range(sim_probs.shape[1]):
            rows[-1][f"prob_clase_{class_idx}_promedio"] = float(sim_probs[:, class_idx].mean())

    result = pd.DataFrame(rows)
    metadata = {
        "n_filas_base": n_rows,
        "baseline_clase_mayoritaria": baseline_majority,
        "baseline_distribucion_clases": {
            f"clase_{int(class_idx)}": float(fraction)
            for class_idx, fraction in baseline_distribution.items()
        },
        "baseline_probabilities": {
            f"prob_clase_{idx}_promedio": float(probability)
            for idx, probability in enumerate(baseline_probs.mean(axis=0))
        },
        "baseline_confianza_promedio": float(np.mean(baseline_confidences)),
        "warnings": warnings_out,
    }
    return result, metadata


def _original_numeric_minmax(series: pd.Series) -> tuple[Any, Any] | None:
    values = pd.to_numeric(series.dropna(), errors="coerce").dropna()
    if values.empty or values.nunique() < 2:
        return None
    return values.min(), values.max()


def _base_original_value(series: pd.Series) -> Any:
    values = pd.to_numeric(series.dropna(), errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.median())


def _risk_score(probabilities: np.ndarray) -> float:
    probs = np.asarray(probabilities, dtype=np.float64)
    class_axis = np.arange(probs.shape[1], dtype=np.float64)
    return float(np.mean(probs @ class_axis))


def _risk_label(value: float, n_classes: int) -> str:
    if n_classes <= 0 or not np.isfinite(value):
        return "riesgo no disponible"
    idx = int(np.clip(round(value), 0, n_classes - 1))
    if n_classes == 4:
        labels = [
            "Riesgo bajo (Q1)",
            "Riesgo medio-bajo (Q2)",
            "Riesgo medio-alto (Q3)",
            "Riesgo alto (Q4)",
        ]
    elif n_classes == 3:
        labels = ["Riesgo bajo", "Riesgo medio", "Riesgo alto"]
    elif n_classes == 2:
        labels = ["Riesgo bajo", "Riesgo alto"]
    else:
        labels = [f"Clase {i}" for i in range(n_classes)]
    return labels[idx]


def _class_label(class_idx: int, n_classes: int) -> str:
    if n_classes == 4:
        labels = [
            "Riesgo bajo (Q1)",
            "Riesgo medio-bajo (Q2)",
            "Riesgo medio-alto (Q3)",
            "Riesgo alto (Q4)",
        ]
    elif n_classes == 3:
        labels = ["Riesgo bajo", "Riesgo medio", "Riesgo alto"]
    elif n_classes == 2:
        labels = ["Riesgo bajo", "Riesgo alto"]
    else:
        labels = [f"Clase {idx}" for idx in range(n_classes)]
    idx = int(np.clip(class_idx, 0, max(n_classes - 1, 0)))
    return labels[idx] if labels else "riesgo no disponible"


def _direction(delta: float, *, tolerance: float) -> str:
    if delta > tolerance:
        return "aumenta riesgo"
    if delta < -tolerance:
        return "disminuye riesgo"
    return "sin cambio relevante"


def _relative_change(delta: float, baseline: float) -> float:
    if abs(baseline) < 1e-12:
        return float("nan")
    return float((delta / baseline) * 100.0)


def _effect_observation(variable: str, min_direction: str, max_direction: str) -> str:
    if min_direction == max_direction:
        if min_direction == "sin cambio relevante":
            return f"{variable}: los extremos observados no modifican de forma relevante el riesgo promedio."
        return f"{variable}: ambos extremos {min_direction.replace(' riesgo', 'n el riesgo')} frente al escenario base."
    return (
        f"{variable}: el mínimo {min_direction.replace(' riesgo', ' el riesgo')} y "
        f"el máximo {max_direction.replace(' riesgo', ' el riesgo')} frente al escenario base."
    )


def simulate_automatic_minmax_sensitivity(
    *,
    model: Any,
    X_scaled: np.ndarray,
    X_raw_model: np.ndarray,
    original_feature_df: pd.DataFrame,
    feature_names: list[str],
    variables: list[str],
    feature_scaler: Any,
    predict_fn: Callable[..., dict[str, Any]],
    device: str,
    mask: np.ndarray | None = None,
    label_encoders: dict[str, Any] | None = None,
    max_values_imputed: dict[str, Any] | None = None,
    batch_size: int = 1024,
    tolerance: float = 1e-6,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run automatic min/max scenarios in original scale for selected numeric variables."""
    X_scaled = np.asarray(X_scaled, dtype=np.float32)
    X_raw_model = np.asarray(X_raw_model, dtype=np.float32)
    if mask is None:
        mask = np.ones(X_scaled.shape[0], dtype=bool)
    mask = np.asarray(mask, dtype=bool)
    if mask.shape[0] != X_scaled.shape[0]:
        raise ValueError("La máscara no tiene la misma longitud que X_scaled.")
    if not mask.any():
        raise ValueError("El subconjunto base está vacío con los filtros seleccionados.")

    unique_variables: list[str] = []
    warnings_out: list[str] = []
    for variable in variables or []:
        text = str(variable).strip()
        if text and text not in unique_variables:
            unique_variables.append(text)

    X_base = X_scaled[mask].copy()
    X_raw_base = X_raw_model[mask].copy()
    baseline_probs, baseline_preds = predict_probabilities(
        model,
        X_base,
        predict_fn=predict_fn,
        device=device,
        batch_size=batch_size,
    )
    baseline_risk = _risk_score(baseline_probs)
    n_classes = int(baseline_probs.shape[1])
    baseline_majority = int(pd.Series(baseline_preds).mode().iloc[0])
    rows: list[dict[str, Any]] = []

    for variable in unique_variables:
        if variable not in feature_names:
            warnings_out.append(f"{variable}: omitida porque no está en feature_names.")
            continue
        if variable not in original_feature_df.columns:
            warnings_out.append(f"{variable}: omitida porque no tiene valores originales disponibles.")
            continue
        minmax = _original_numeric_minmax(original_feature_df[variable])
        if minmax is None:
            warnings_out.append(f"{variable}: omitida porque no tiene mínimo/máximo numérico válido.")
            continue

        min_value, max_value = minmax
        base_value = _base_original_value(original_feature_df.loc[mask, variable])
        feature_idx = feature_names.index(variable)
        scenario_results: dict[str, dict[str, Any]] = {}
        for scenario_name, original_value in (("minimo", min_value), ("maximo", max_value)):
            try:
                transformed_value = transform_single_feature_value(
                    variable,
                    original_value,
                    baseline_raw_row=X_raw_base[0],
                    feature_names=feature_names,
                    feature_scaler=feature_scaler,
                    label_encoders=label_encoders,
                    max_values_imputed=max_values_imputed,
                )
            except Exception as exc:
                warnings_out.append(f"{variable}={original_value}: {exc}")
                continue
            X_sim = X_base.copy()
            X_sim[:, feature_idx] = transformed_value
            sim_probs, sim_preds = predict_probabilities(
                model,
                X_sim,
                predict_fn=predict_fn,
                device=device,
                batch_size=batch_size,
            )
            risk = _risk_score(sim_probs)
            delta = risk - baseline_risk
            scenario_results[scenario_name] = {
                "risk": risk,
                "label": _risk_label(risk, n_classes),
                "majority": int(pd.Series(sim_preds).mode().iloc[0]),
                "delta": delta,
                "relative": _relative_change(delta, baseline_risk),
                "direction": _direction(delta, tolerance=tolerance),
            }
        if "minimo" not in scenario_results or "maximo" not in scenario_results:
            continue

        min_result = scenario_results["minimo"]
        max_result = scenario_results["maximo"]
        rows.append(
            {
                "variable": variable,
                "valor_original_base": base_value,
                "valor_minimo_usado": float(min_value),
                "valor_maximo_usado": float(max_value),
                "riesgo_base": baseline_risk,
                "riesgo_base_etiqueta": _risk_label(baseline_risk, n_classes),
                "clase_mayoritaria_base": baseline_majority,
                "riesgo_valor_minimo": min_result["risk"],
                "riesgo_valor_minimo_etiqueta": min_result["label"],
                "clase_mayoritaria_minimo": min_result["majority"],
                "riesgo_valor_maximo": max_result["risk"],
                "riesgo_valor_maximo_etiqueta": max_result["label"],
                "clase_mayoritaria_maximo": max_result["majority"],
                "cambio_absoluto_minimo": min_result["delta"],
                "cambio_absoluto_maximo": max_result["delta"],
                "cambio_relativo_minimo_pct": min_result["relative"],
                "cambio_relativo_maximo_pct": max_result["relative"],
                "direccion_cambio_minimo": min_result["direction"],
                "direccion_cambio_maximo": max_result["direction"],
                "magnitud_max_cambio_abs": max(abs(min_result["delta"]), abs(max_result["delta"])),
                "observacion": _effect_observation(
                    variable,
                    str(min_result["direction"]),
                    str(max_result["direction"]),
                ),
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("magnitud_max_cambio_abs", ascending=False, kind="stable").reset_index(drop=True)
    metadata = {
        "n_filas_base": int(mask.sum()),
        "n_variables_recibidas": len(unique_variables),
        "n_variables_simuladas": int(len(result)),
        "riesgo_base": baseline_risk,
        "riesgo_base_etiqueta": _risk_label(baseline_risk, n_classes),
        "clase_mayoritaria_base": baseline_majority,
        "warnings": warnings_out,
    }
    return result, metadata


def _select_top_softmax_variables(
    automatic_simulation_table: pd.DataFrame | None,
    variables: list[str] | None,
    *,
    max_variables: int,
) -> list[str]:
    selected: list[str] = []
    if automatic_simulation_table is not None and not automatic_simulation_table.empty:
        table = automatic_simulation_table.copy()
        if "variable" in table.columns:
            for col in ["magnitud_max_cambio_abs", "cambio_absoluto_minimo", "cambio_absoluto_maximo"]:
                if col not in table.columns:
                    table[col] = 0.0
                table[col] = pd.to_numeric(table[col], errors="coerce").fillna(0.0)
            table["_impacto_softmax"] = table[
                ["magnitud_max_cambio_abs", "cambio_absoluto_minimo", "cambio_absoluto_maximo"]
            ].abs().max(axis=1)
            table = table.sort_values("_impacto_softmax", ascending=False, kind="stable")
            for variable in table["variable"].fillna("").astype(str):
                text = variable.strip()
                if text and text not in selected:
                    selected.append(text)
                if len(selected) >= max_variables:
                    return selected
    for variable in variables or []:
        text = str(variable or "").strip()
        if text and text not in selected:
            selected.append(text)
        if len(selected) >= max_variables:
            break
    return selected


def simulate_top_softmax_curves(
    *,
    model: Any,
    X_scaled: np.ndarray,
    X_raw_model: np.ndarray,
    original_feature_df: pd.DataFrame,
    feature_names: list[str],
    variables: list[str] | None,
    feature_scaler: Any,
    predict_fn: Callable[..., dict[str, Any]],
    device: str,
    mask: np.ndarray,
    automatic_simulation_table: pd.DataFrame | None = None,
    label_encoders: dict[str, Any] | None = None,
    max_values_imputed: dict[str, Any] | None = None,
    batch_size: int = 1024,
    max_variables: int = 4,
    max_values: int = 18,
) -> dict[str, Any]:
    """Build class-probability curves for the most relevant simulated variables."""
    warnings_out: list[str] = []
    curve_variables = _select_top_softmax_variables(
        automatic_simulation_table,
        variables,
        max_variables=max_variables,
    )
    if not curve_variables:
        return {
            "variables": [],
            "metadata": {
                "max_variables": max_variables,
                "max_values": max_values,
                "warnings": ["No hay variables candidatas para construir curvas softmax."],
            },
        }

    mask = np.asarray(mask, dtype=bool)
    curves: list[dict[str, Any]] = []
    for variable in curve_variables:
        if variable not in feature_names:
            warnings_out.append(f"{variable}: omitida en curvas softmax porque no está en feature_names.")
            continue
        if variable not in original_feature_df.columns:
            warnings_out.append(f"{variable}: omitida en curvas softmax porque no tiene valores originales.")
            continue
        values = default_simulation_values(original_feature_df.loc[mask, variable], max_values=max_values)
        if not values:
            warnings_out.append(f"{variable}: omitida en curvas softmax porque no tiene valores simulables.")
            continue
        try:
            result, metadata = simulate_feature_class_transitions(
                model=model,
                X_scaled=X_scaled,
                X_raw_model=X_raw_model,
                original_feature_df=original_feature_df,
                feature_names=feature_names,
                variable=variable,
                values_original=values,
                feature_scaler=feature_scaler,
                predict_fn=predict_fn,
                device=device,
                mask=mask,
                label_encoders=label_encoders,
                max_values_imputed=max_values_imputed,
                batch_size=batch_size,
            )
        except Exception as exc:
            warnings_out.append(f"{variable}: no se pudo construir curva softmax: {exc}")
            continue
        if result.empty:
            warnings_out.append(f"{variable}: la curva softmax no produjo filas válidas.")
            continue
        prob_cols = sorted(
            [col for col in result.columns if col.startswith("prob_clase_") and col.endswith("_promedio")],
            key=lambda name: int(name.split("_")[2]),
        )
        if not prob_cols:
            warnings_out.append(f"{variable}: la curva softmax no incluye probabilidades por clase.")
            continue
        n_classes = len(prob_cols)
        rows: list[dict[str, Any]] = []
        best_row: dict[str, Any] | None = None
        for raw_row in result.to_dict(orient="records"):
            class_probs = {
                _class_label(idx, n_classes): float(raw_row.get(col, 0.0) or 0.0)
                for idx, col in enumerate(prob_cols)
            }
            risk_score = float(sum(idx * probability for idx, probability in enumerate(class_probs.values())))
            majority = int(raw_row.get("clase_mayoritaria_simulada", round(risk_score)) or 0)
            row = {
                "valor_original": raw_row.get("valor_original"),
                "riesgo_ordinal_estimado": risk_score,
                "clase_estimacion": _risk_label(risk_score, n_classes),
                "clase_mayoritaria_simulada": _class_label(majority, n_classes),
                "probabilidades": class_probs,
            }
            rows.append(row)
            if best_row is None or risk_score < float(best_row.get("riesgo_ordinal_estimado", np.inf)):
                best_row = row
        curves.append(
            {
                "variable": variable,
                "n_clases": n_classes,
                "etiquetas_clase": [_class_label(idx, n_classes) for idx in range(n_classes)],
                "valores_probados": values,
                "filas": rows,
                "mejor_escenario_menor_riesgo": best_row or {},
                "metadata": metadata,
            }
        )

    return {
        "variables": curves,
        "metadata": {
            "max_variables": max_variables,
            "max_values": max_values,
            "variables_solicitadas": curve_variables,
            "variables_graficadas": [item["variable"] for item in curves],
            "warnings": warnings_out,
        },
    }


def _risk_reduction_softmax_values(curves: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Select suggested values from softmax curves using lowest dominant class priority."""
    if not isinstance(curves, dict):
        return [], []
    variables = [item for item in (curves.get("variables") or []) if isinstance(item, dict) and item.get("filas")]

    def label_rank(label: Any) -> int:
        text = str(label or "").lower()
        if "q1" in text or ("bajo" in text and "medio" not in text):
            return 0
        if "q2" in text or "medio-bajo" in text or ("medio" in text and "alto" not in text):
            return 1
        if "q3" in text or "medio-alto" in text:
            return 2
        if "q4" in text or "alto" in text:
            return 3
        return 4

    def dominant_label(row: dict[str, Any]) -> str:
        probs = row.get("probabilidades") if isinstance(row.get("probabilidades"), dict) else {}
        if not probs:
            return ""
        return str(max(probs, key=lambda label: float(probs.get(label, 0.0) or 0.0)))

    selected: list[dict[str, Any]] = []
    kept: list[str] = []
    for item in variables:
        variable = str(item.get("variable", "")).strip()
        candidates = []
        for row in [row for row in item.get("filas", []) if isinstance(row, dict)]:
            dominant = dominant_label(row)
            rank = label_rank(dominant)
            probs = row.get("probabilidades") if isinstance(row.get("probabilidades"), dict) else {}
            probability = float(probs.get(dominant, 0.0) or 0.0)
            candidates.append(
                (
                    rank,
                    -probability,
                    float(row.get("riesgo_ordinal_estimado", 99.0) or 99.0),
                    row,
                    dominant,
                    probability,
                )
            )
        valid = [candidate for candidate in candidates if candidate[0] < 3]
        if not valid:
            if variable:
                kept.append(variable)
            continue
        rank, _, risk_score, row, dominant, probability = sorted(valid, key=lambda candidate: candidate[:3])[0]
        selected.append(
            {
                "variable": variable,
                "valor": row.get("valor_original"),
                "clase_dominante": dominant,
                "probabilidad_dominante": probability,
                "riesgo_ordinal_estimado": risk_score,
            }
        )
    return selected, kept


def simulate_suggested_vano_risk(
    *,
    model: Any,
    X_scaled: np.ndarray,
    X_raw_model: np.ndarray,
    feature_names: list[str],
    feature_scaler: Any,
    predict_fn: Callable[..., dict[str, Any]],
    device: str,
    mask: np.ndarray,
    vano_ids: pd.Series | np.ndarray | list[Any],
    softmax_curves: dict[str, Any] | None,
    label_encoders: dict[str, Any] | None = None,
    max_values_imputed: dict[str, Any] | None = None,
    batch_size: int = 1024,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Simulate selected softmax values and aggregate predicted probabilities by FID_VANO.

    Multiple records for the same vano are handled by averaging class probabilities per vano.
    Averaging is intentional: summing probabilities would overweight vanos with more rows.
    """
    X_scaled = np.asarray(X_scaled, dtype=np.float32)
    X_raw_model = np.asarray(X_raw_model, dtype=np.float32)
    mask = np.asarray(mask, dtype=bool)
    if mask.shape[0] != X_scaled.shape[0]:
        raise ValueError("La máscara no tiene la misma longitud que X_scaled.")
    if not mask.any():
        raise ValueError("El subconjunto base está vacío con los filtros seleccionados.")
    vano_series = pd.Series(vano_ids).reset_index(drop=True)
    if len(vano_series) != X_scaled.shape[0]:
        raise ValueError("vano_ids debe tener la misma longitud que X_scaled.")

    selected, kept = _risk_reduction_softmax_values(softmax_curves)
    X_base = X_scaled[mask].copy()
    X_raw_base = X_raw_model[mask].copy()
    base_vanos = vano_series.loc[mask].fillna("").astype(str).reset_index(drop=True)
    baseline_probs, _ = predict_probabilities(
        model,
        X_base,
        predict_fn=predict_fn,
        device=device,
        batch_size=batch_size,
    )
    n_classes = int(baseline_probs.shape[1])
    class_labels = [_class_label(idx, n_classes) for idx in range(n_classes)]

    X_sim = X_base.copy()
    applied: list[dict[str, Any]] = []
    warnings_out: list[str] = []
    for item in selected:
        variable = str(item.get("variable", "")).strip()
        if variable not in feature_names:
            kept.append(variable)
            warnings_out.append(f"{variable}: no se aplicó porque no está en feature_names.")
            continue
        try:
            transformed_value = transform_single_feature_value(
                variable,
                item.get("valor"),
                baseline_raw_row=X_raw_base[0],
                feature_names=feature_names,
                feature_scaler=feature_scaler,
                label_encoders=label_encoders,
                max_values_imputed=max_values_imputed,
            )
        except Exception as exc:
            kept.append(variable)
            warnings_out.append(f"{variable}: no se aplicó valor sugerido {item.get('valor')}: {exc}")
            continue
        X_sim[:, feature_names.index(variable)] = transformed_value
        applied.append(item)

    sim_probs, _ = predict_probabilities(
        model,
        X_sim,
        predict_fn=predict_fn,
        device=device,
        batch_size=batch_size,
    )

    def aggregate_probs(probs: np.ndarray, prefix: str) -> pd.DataFrame:
        prob_df = pd.DataFrame(probs, columns=[f"{prefix}_prob_clase_{idx}" for idx in range(n_classes)])
        prob_df.insert(0, "FID_VANO", base_vanos.to_numpy())
        grouped = prob_df.groupby("FID_VANO", dropna=False).mean()
        counts = prob_df.groupby("FID_VANO", dropna=False).size().rename("n_registros")
        grouped = grouped.join(counts)
        prob_cols = [f"{prefix}_prob_clase_{idx}" for idx in range(n_classes)]
        argmax_idx = grouped[prob_cols].to_numpy().argmax(axis=1)
        grouped[f"{prefix}_clase_idx"] = argmax_idx
        grouped[f"{prefix}_clase"] = [class_labels[idx] for idx in argmax_idx]
        class_axis = np.arange(n_classes, dtype=np.float64)
        grouped[f"{prefix}_riesgo_ordinal"] = grouped[prob_cols].to_numpy() @ class_axis
        return grouped

    baseline_grouped = aggregate_probs(baseline_probs, "base")
    simulated_grouped = aggregate_probs(sim_probs, "simulado").drop(columns=["n_registros"])
    result = baseline_grouped.join(simulated_grouped, how="outer").reset_index()
    result["delta_riesgo_ordinal"] = result["simulado_riesgo_ordinal"] - result["base_riesgo_ordinal"]
    result["variables_aplicadas"] = ", ".join(item["variable"] for item in applied)
    result["variables_quietas"] = ", ".join(sorted(set(variable for variable in kept if variable)))

    metadata = {
        "n_vanos": int(result["FID_VANO"].nunique()),
        "n_registros": int(mask.sum()),
        "agregacion": "promedio_probabilidades_por_vano",
        "variables_aplicadas": applied,
        "variables_quietas": sorted(set(variable for variable in kept if variable)),
        "warnings": warnings_out,
    }
    return result, metadata


def save_auto_minmax_results(result_df: pd.DataFrame, path: str | Path) -> Path:
    if result_df.empty:
        raise ValueError("La tabla del simulador automático está vacía; no se guarda archivo.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_excel(target, index=False)
    return target


def safe_plot_filename(variable: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", str(variable)).strip("_")
    return f"Sim_{slug or 'variable'}.pdf"


def make_value_widget(variable: str, Xdf: pd.DataFrame, *, label_encoders: dict[str, Any] | None = None):
    """Create an ipywidgets control for one simulator variable."""
    import ipywidgets as widgets

    label_encoders = label_encoders or {}
    if is_categorical_variable(variable, Xdf, label_encoders):
        values = categorical_values_for_variable(variable, Xdf, label_encoders=label_encoders)
        text = f"Categorica: se evaluaran automaticamente {len(values)} categorias."
        return widgets.HTML(value=f"<b>Valor</b>: {text}")

    numeric = pd.to_numeric(Xdf[variable], errors="coerce").dropna()
    if numeric.empty:
        return widgets.Text(value="", description="Valor")
    min_value = float(numeric.min())
    max_value = float(numeric.max())
    median_value = float(numeric.median())
    if np.isclose(min_value, max_value):
        return widgets.FloatText(value=median_value, description="Valor")
    step = max((max_value - min_value) / 100.0, 1e-6)
    return widgets.FloatSlider(
        value=median_value,
        min=min_value,
        max=max_value,
        step=step,
        description="Valor",
        continuous_update=False,
        readout_format=".4g",
    )


def save_simulation_outputs(
    result_df: pd.DataFrame,
    variable: str,
    *,
    output_dir: str | Path,
    plots_dir: str | Path,
    results_path: str | Path,
    class_labels: list[str],
):
    """Save simulator table and softmax plot outputs."""
    import matplotlib.pyplot as plt

    output_dir = Path(output_dir)
    plots_dir = Path(plots_dir)
    results_path = Path(results_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    result_df.to_excel(results_path, index=False)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    plot_df = result_df.copy()
    try:
        plot_df["_x"] = pd.to_numeric(plot_df["valor_original"], errors="raise")
        plot_df = plot_df.sort_values("_x")
        x_values = plot_df["_x"]
        ax.set_xlabel(variable)
    except Exception:
        plot_df["_x"] = plot_df["valor_original"].astype(str)
        x_values = plot_df["_x"]
        ax.set_xlabel(variable)
        ax.tick_params(axis="x", rotation=45)

    for class_idx, label in enumerate(class_labels):
        column = f"prob_clase_{class_idx}_promedio"
        if column in plot_df.columns:
            ax.plot(x_values, plot_df[column], marker="o", linewidth=2, label=label)

    ax.set_ylabel("Probabilidad softmax promedio")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    ax.set_title(f"Softmax por clase según {variable}")
    fig.tight_layout()
    pdf_path = plots_dir / safe_plot_filename(variable)
    png_path = pdf_path.with_suffix(".png")
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    return fig, png_path

