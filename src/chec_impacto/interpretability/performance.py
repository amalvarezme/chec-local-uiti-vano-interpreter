"""Performance interpretation helpers for MGCECDL notebooks."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap


def expand_selected_variables(
    variables: list[str] | tuple[str, ...],
    *,
    selected_names: set[str],
    features: list[str],
    climate_prefixes: set[str],
    excluded: set[str] | None = None,
) -> list[str]:
    """Expand selected variables, mapping climate families to lagged feature columns."""
    excluded = excluded or {"UITI_VANO"}
    columns = []
    for variable in variables:
        if variable not in selected_names or variable in excluded:
            continue
        if variable in climate_prefixes:
            columns.extend(feature for feature in features if feature.startswith(f"{variable}_"))
        elif variable in features:
            columns.append(variable)
    return list(dict.fromkeys(columns))


def absolute_shap_matrix(shap_values, n_features: int) -> np.ndarray:
    """Normalize SHAP values into an absolute sample-by-feature matrix."""
    if isinstance(shap_values, list):
        matrices = [np.asarray(values) for values in shap_values]
        return np.mean(np.abs(np.stack(matrices, axis=0)), axis=0)

    values = np.asarray(shap_values)
    if values.ndim == 2:
        return np.abs(values)
    if values.ndim == 3 and values.shape[1] == n_features:
        return np.mean(np.abs(values), axis=2)
    if values.ndim == 3 and values.shape[2] == n_features:
        return np.mean(np.abs(values), axis=0)
    raise ValueError(f"Formato SHAP no soportado: {values.shape}")


def build_shap_predict_fn(model, x_background: np.ndarray, predict_fn: Callable, *, device):
    """Build a Kernel SHAP prediction function with singleton-batch protection."""

    def predict_shap(values):
        values = np.asarray(values, dtype=np.float32)
        if values.ndim == 1:
            values = values.reshape(1, -1)
        singleton = len(values) == 1
        if singleton:
            values = np.vstack([values, x_background[0:1]])

        predictions = np.asarray(predict_fn(model, values, device=device)["fused_probs"])
        return predictions[:1] if singleton else predictions

    return predict_shap


def generate_shap_mode_radars(
    models: Mapping[str, object],
    x_reference,
    output_path: str | Path,
    *,
    features: list[str],
    modes_radar: Mapping[str, list[str]],
    predict_fn: Callable,
    device,
    model_name: str = "MGCECDL",
    results_dir: str | Path | None = None,
    site_results_dir: str | Path | None = None,
    background_size: int = 50,
    sample_size: int = 1000,
    nsamples: int = 300,
    seed: int = 42,
    figure_title: str | None = None,
) -> dict[str, pd.Series]:
    """Generate SHAP radar/bar figures by CHEC mode for the classifier model."""
    if "clasificacion" not in models:
        print(f"No hay clasificador {model_name} disponible para calcular radar SHAP.")
        return {}

    rng = np.random.default_rng(seed)
    x_reference = np.asarray(x_reference, dtype=np.float32)
    if x_reference.shape[1] != len(features):
        raise ValueError("El número de columnas no coincide con las características del modelo.")

    bg_idx = rng.choice(len(x_reference), size=min(background_size, len(x_reference)), replace=False)
    eval_idx = rng.choice(len(x_reference), size=min(sample_size, len(x_reference)), replace=False)
    x_background = x_reference[bg_idx]
    x_eval = x_reference[eval_idx]

    print(f"Calculando SHAP {model_name} - clasificacion...")
    predict_shap = build_shap_predict_fn(models["clasificacion"], x_background, predict_fn, device=device)
    explainer = shap.KernelExplainer(predict_shap, x_background)
    shap_values = explainer.shap_values(x_eval, nsamples=nsamples)
    shap_abs = absolute_shap_matrix(shap_values, len(features))
    df_shap = pd.DataFrame(shap_abs, columns=features)

    scores = pd.Series(
        {
            name: float(df_shap[columns].sum(axis=1).mean())
            for name, columns in modes_radar.items()
        },
        name="atribucion_shap_media",
    )
    model_scores = {"clasificacion": scores}

    maximum = scores.max() * 1.15
    fig, ax = plt.subplots(1, 1, figsize=(9, 8), subplot_kw={"polar": True})
    angles = np.linspace(0, 2 * np.pi, len(scores), endpoint=False)
    ax.plot(np.r_[angles, angles[0]], np.r_[scores.values, scores.values[0]], color="#7f3f98", linewidth=2.4)
    ax.fill(np.r_[angles, angles[0]], np.r_[scores.values, scores.values[0]], color="#b07cc6", alpha=0.35)
    ax.scatter(angles, scores.values, color="#55246b", s=50, zorder=3)
    ax.set_xticks(angles)
    ax.set_xticklabels(scores.index, fontsize=8.5, fontweight="bold")
    ax.tick_params(axis="x", pad=22)
    ax.set_ylim(0, maximum if maximum > 0 else 1.0)
    ax.grid(alpha=0.35)
    ax.set_title("Kernel SHAP - Clasificacion", fontsize=14, fontweight="bold", pad=36)
    if figure_title is None:
        figure_title = f"{model_name} - atribución SHAP por modos"
    fig.suptitle(figure_title, fontsize=16, fontweight="bold", y=0.99)
    fig.subplots_adjust(top=0.82, bottom=0.12, left=0.06, right=0.94, wspace=0.32)
    output_path = Path(output_path)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    if site_results_dir is not None:
        fig.savefig(Path(site_results_dir) / "mgcecdl_mode_importance_radar.png", dpi=180, bbox_inches="tight")
    plt.show()

    if results_dir is not None:
        fig_bar, ax_bar = plt.subplots(1, 1, figsize=(9.5, 5.8))
        scores.sort_values().plot(kind="barh", ax=ax_bar, color="#0b5f8a")
        ax_bar.set_title("Importancia media por modo (Kernel SHAP)", pad=14, fontweight="bold")
        ax_bar.set_xlabel("Atribución SHAP media")
        ax_bar.grid(axis="x", alpha=0.3)
        fig_bar.tight_layout()
        fig_bar.savefig(Path(results_dir) / "mgcecdl_mode_importance.png", dpi=180, bbox_inches="tight")
        if site_results_dir is not None:
            fig_bar.savefig(Path(site_results_dir) / "mgcecdl_mode_importance.png", dpi=180, bbox_inches="tight")
        plt.show()
        print("Figura web actualizada: mgcecdl_mode_importance.png")

    return model_scores
