from __future__ import annotations

import re
import warnings
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


def build_context_mask(
    context_df: pd.DataFrame,
    filters: dict[str, Any] | None,
) -> np.ndarray:
    mask = np.ones(len(context_df), dtype=bool)
    filters = filters or {}
    for column, value in filters.items():
        if column not in context_df.columns or value in (None, "", "Todos"):
            continue
        mask &= context_df[column].astype(str).eq(str(value)).to_numpy()
    return mask


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


def warn_messages(messages: list[str]) -> None:
    for message in messages:
        warnings.warn(message, RuntimeWarning, stacklevel=2)
