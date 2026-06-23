"""Interpretability helpers for CHEC M-GCECDL classification workflows."""

from __future__ import annotations

from pathlib import Path

import matplotlib.path as mpath
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _select_target_support(
    modality_probs: np.ndarray,
    fused_probs: np.ndarray,
    target_labels: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    fused_probs = np.asarray(fused_probs)
    modality_probs = np.asarray(modality_probs)

    if target_labels is None:
        target_labels = fused_probs.argmax(axis=1)
    else:
        target_labels = np.asarray(target_labels).reshape(-1).astype(int)

    if modality_probs.ndim != 3:
        raise ValueError(
            f"Expected modality_probs with shape (n_samples, n_modalities, n_classes), got {modality_probs.shape}."
        )

    selected_modality_probs = np.take_along_axis(
        modality_probs,
        target_labels[:, None, None],
        axis=2,
    ).squeeze(2)
    selected_fused_probs = np.take_along_axis(
        fused_probs,
        target_labels[:, None],
        axis=1,
    ).squeeze(1)
    return selected_modality_probs, selected_fused_probs


def summarize_classification_modality_support(
    modality_names: tuple[str, ...] | list[str],
    reliabilities: np.ndarray,
    modality_probs: np.ndarray,
    fused_probs: np.ndarray,
    target_labels: np.ndarray | None = None,
) -> pd.DataFrame:
    """Aggregate modality reliabilities and class-support contributions for classification."""
    reliabilities = np.asarray(reliabilities)
    selected_modality_probs, _ = _select_target_support(
        modality_probs=modality_probs,
        fused_probs=fused_probs,
        target_labels=target_labels,
    )
    confidence_contributions = reliabilities * selected_modality_probs

    summary = pd.DataFrame(
        {
            "modality": list(modality_names),
            "mean_reliability": reliabilities.mean(axis=0),
            "mean_target_class_probability": selected_modality_probs.mean(axis=0),
            "mean_confidence_contribution": confidence_contributions.mean(axis=0),
            "mean_abs_contribution": confidence_contributions.mean(axis=0),
        }
    ).sort_values("mean_confidence_contribution", ascending=False)
    return summary.reset_index(drop=True)


def summarize_modality_reliability_by_class(
    modality_names: tuple[str, ...] | list[str],
    reliabilities: np.ndarray,
    targets: np.ndarray,
) -> pd.DataFrame:
    """Summarize mean modality reliability per class label."""
    reliabilities = np.asarray(reliabilities)
    targets = np.asarray(targets).reshape(-1)

    rows: list[dict[str, float | int | str]] = []
    for class_label in sorted(np.unique(targets)):
        class_mask = targets == class_label
        class_reliabilities = reliabilities[class_mask]
        for modality_index, modality_name in enumerate(modality_names):
            rows.append(
                {
                    "class_label": int(class_label),
                    "modality": modality_name,
                    "mean_reliability": float(class_reliabilities[:, modality_index].mean()),
                    "n_samples": int(class_mask.sum()),
                }
            )

    return pd.DataFrame(rows)


def build_classification_modality_outputs_per_sample(
    modality_names: tuple[str, ...] | list[str],
    reliabilities: np.ndarray,
    modality_probs: np.ndarray,
    fused_probs: np.ndarray,
    targets: np.ndarray | None = None,
) -> pd.DataFrame:
    """Build a per-sample dataframe with fused probabilities and modality outputs."""
    reliabilities = np.asarray(reliabilities)
    modality_probs = np.asarray(modality_probs)
    fused_probs = np.asarray(fused_probs)
    predicted_classes = fused_probs.argmax(axis=1)
    selected_modality_probs, selected_fused_probs = _select_target_support(
        modality_probs=modality_probs,
        fused_probs=fused_probs,
        target_labels=predicted_classes,
    )
    support_predicted = reliabilities * selected_modality_probs

    data: dict[str, np.ndarray] = {
        "sample_index": np.arange(fused_probs.shape[0]),
        "y_pred": predicted_classes.astype(int),
        "fused_probability_predicted_class": selected_fused_probs,
    }
    if targets is not None:
        data["y_true"] = np.asarray(targets).reshape(-1).astype(int)

    for class_index in range(fused_probs.shape[1]):
        data[f"fused_prob__class_{class_index}"] = fused_probs[:, class_index]

    for modality_index, modality_name in enumerate(modality_names):
        data[f"reliability__{modality_name}"] = reliabilities[:, modality_index]
        data[f"support_predicted__{modality_name}"] = support_predicted[:, modality_index]
        for class_index in range(modality_probs.shape[2]):
            data[f"modality_prob__{modality_name}__class_{class_index}"] = modality_probs[
                :, modality_index, class_index
            ]

    return pd.DataFrame(data)


def _resolve_class_values(
    n_classes: int,
    class_values: np.ndarray | list[float] | None = None,
) -> np.ndarray:
    if class_values is None:
        return np.arange(n_classes, dtype=float)

    class_values_array = np.asarray(class_values, dtype=float).reshape(-1)
    if class_values_array.shape[0] != n_classes:
        raise ValueError(
            f"Expected {n_classes} class values, got {class_values_array.shape[0]}."
        )
    return class_values_array


def build_classification_expected_class_outputs(
    modality_names: tuple[str, ...] | list[str],
    modality_probs: np.ndarray,
    fused_probs: np.ndarray,
    targets: np.ndarray | None = None,
    class_values: np.ndarray | list[float] | None = None,
) -> pd.DataFrame:
    """Build per-sample expected-class outputs from modality and fused probabilities."""
    modality_probs = np.asarray(modality_probs, dtype=float)
    fused_probs = np.asarray(fused_probs, dtype=float)

    if modality_probs.ndim != 3:
        raise ValueError(
            f"Expected modality_probs with shape (n_samples, n_modalities, n_classes), got {modality_probs.shape}."
        )
    if fused_probs.ndim != 2:
        raise ValueError(
            f"Expected fused_probs with shape (n_samples, n_classes), got {fused_probs.shape}."
        )
    if modality_probs.shape[0] != fused_probs.shape[0]:
        raise ValueError("modality_probs and fused_probs must have the same number of samples.")
    if modality_probs.shape[2] != fused_probs.shape[1]:
        raise ValueError("modality_probs and fused_probs must agree on the number of classes.")

    class_values_array = _resolve_class_values(
        n_classes=fused_probs.shape[1],
        class_values=class_values,
    )
    modality_expected_classes = np.tensordot(
        modality_probs,
        class_values_array,
        axes=([2], [0]),
    )
    fused_expected_classes = fused_probs @ class_values_array
    predicted_classes = fused_probs.argmax(axis=1).astype(int)

    data: dict[str, np.ndarray] = {
        "sample_index": np.arange(fused_probs.shape[0]),
        "y_pred": predicted_classes,
        "fused_expected_class": fused_expected_classes,
    }
    if targets is not None:
        data["y_true"] = np.asarray(targets).reshape(-1).astype(float)

    for modality_index, modality_name in enumerate(modality_names):
        data[f"expected_class__{modality_name}"] = modality_expected_classes[:, modality_index]

    return pd.DataFrame(data)


def plot_classification_modality_expected_classes(
    modality_names: tuple[str, ...] | list[str],
    modality_probs: np.ndarray,
    fused_probs: np.ndarray,
    targets: np.ndarray | None = None,
    label_map: dict[str, str] | None = None,
    class_values: np.ndarray | list[float] | None = None,
    sort_by: str | None = "y_true",
    sample_step: int | None = None,
    smooth_window: int | None = None,
    include_fused: bool = True,
    include_y_true: bool = True,
    figsize: tuple[int, int] = (16, 7),
    title: str = "Predicciones por modalidad en clases numericas",
    output_path: str | Path | None = None,
    show_plot: bool = True,
) -> pd.DataFrame:
    """Plot modality expected-class predictions using class indices as numeric values."""
    comparison_source_df = build_classification_expected_class_outputs(
        modality_names=modality_names,
        modality_probs=modality_probs,
        fused_probs=fused_probs,
        targets=targets,
        class_values=class_values,
    )

    modality_names_list = list(modality_names)
    display_names = [label_map.get(name, name) if label_map else name for name in modality_names_list]
    modality_columns = [f"expected_class__{name}" for name in modality_names_list]
    plot_matrix = comparison_source_df[modality_columns].to_numpy(dtype=float)
    fused_line = comparison_source_df["fused_expected_class"].to_numpy(dtype=float)
    y_true_line = (
        None
        if "y_true" not in comparison_source_df.columns
        else comparison_source_df["y_true"].to_numpy(dtype=float)
    )
    class_values_array = _resolve_class_values(
        n_classes=np.asarray(fused_probs).shape[1],
        class_values=class_values,
    )

    if sort_by == "fused":
        order = np.argsort(fused_line)
    elif sort_by == "y_true" and y_true_line is not None:
        order = np.argsort(y_true_line)
    else:
        order = np.arange(plot_matrix.shape[0])

    plot_matrix = plot_matrix[order]
    fused_line = fused_line[order]
    if y_true_line is not None:
        y_true_line = y_true_line[order]

    if sample_step is None:
        sample_step = max(1, len(fused_line) // 400)

    sample_idx = np.arange(0, len(fused_line), sample_step)
    plot_matrix = plot_matrix[sample_idx]
    fused_line = fused_line[sample_idx]
    if y_true_line is not None:
        y_true_line = y_true_line[sample_idx]

    if smooth_window is not None and smooth_window > 1:
        plot_matrix = (
            pd.DataFrame(plot_matrix)
            .rolling(smooth_window, center=True, min_periods=1)
            .mean()
            .to_numpy()
        )
        fused_line = (
            pd.Series(fused_line)
            .rolling(smooth_window, center=True, min_periods=1)
            .mean()
            .to_numpy()
        )
        if y_true_line is not None:
            y_true_line = (
                pd.Series(y_true_line)
                .rolling(smooth_window, center=True, min_periods=1)
                .mean()
                .to_numpy()
            )

    x_axis = np.arange(len(fused_line))
    colors = plt.cm.tab10(np.linspace(0, 1, len(display_names)))

    fig, ax = plt.subplots(figsize=figsize)
    for modality_index, (display_name, color) in enumerate(zip(display_names, colors)):
        ax.plot(
            x_axis,
            plot_matrix[:, modality_index],
            label=display_name,
            color=color,
            linewidth=1.5,
            alpha=0.9,
        )

    if include_fused:
        ax.plot(
            x_axis,
            fused_line,
            label="fusionado_esperado",
            color="black",
            linewidth=2.8,
            linestyle="--",
        )

    if include_y_true and y_true_line is not None:
        ax.plot(
            x_axis,
            y_true_line,
            label="y_real",
            color="#7f7f7f",
            linewidth=2.0,
            alpha=0.85,
        )

    if np.allclose(class_values_array, np.round(class_values_array)):
        ax.set_yticks(class_values_array)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Muestras ordenadas" if sort_by in {"fused", "y_true"} else "Indice de muestra")
    ax.set_ylabel("Clase numerica")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), frameon=False)
    fig.tight_layout()

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight")

    if show_plot:
        plt.show()
    plt.close(fig)

    comparison_df = pd.DataFrame(plot_matrix, columns=display_names)
    if include_fused:
        comparison_df["fusionado_esperado"] = fused_line
    if include_y_true and y_true_line is not None:
        comparison_df["y_real"] = y_true_line

    return comparison_df


def plot_classification_modality_radar(
    modality_names: tuple[str, ...] | list[str],
    reliabilities: np.ndarray,
    modality_probs: np.ndarray | None = None,
    fused_probs: np.ndarray | None = None,
    label_map: dict[str, str] | None = None,
    target_labels: np.ndarray | None = None,
    cmap_name: str = "RdYlGn_r",
    figsize: tuple[int, int] = (9, 9),
    title: str = "M-GCECDL Mean Modality Reliability",
    output_path: str | Path | None = None,
    show_plot: bool = True,
) -> pd.Series:
    """Plot a radar chart using mean modality reliability per sample."""
    del modality_probs, fused_probs, target_labels

    support_scores = pd.Series(
        np.nanmean(np.asarray(reliabilities), axis=0),
        index=list(modality_names),
        name="mean_reliability",
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    categories = [label_map.get(name, name) if label_map else name for name in support_scores.index]
    values = support_scores.values.astype(float).tolist()

    if len(values) == 0 or np.allclose(values, 0.0):
        return support_scores

    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    values_loop = values + values[:1]
    angles_loop = angles + angles[:1]

    max_val = float(max(values)) * 1.2
    if max_val <= 0 or not np.isfinite(max_val):
        max_val = 1.0

    fig, ax = plt.subplots(figsize=figsize, subplot_kw={"polar": True})
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, max_val)

    cmap = plt.get_cmap(cmap_name)
    norm = plt.Normalize(vmin=min(values), vmax=max(values))

    for angle, value, label in zip(angles, values, categories):
        ax.plot([angle, angle], [0, value], color=cmap(norm(value)), linewidth=2.5, alpha=0.95)
        ax.scatter([angle], [value], color=cmap(norm(value)), s=90, zorder=3)
        ax.text(angle, max_val * 1.06, label, ha="center", va="center", fontsize=11)

    path = mpath.Path(np.column_stack([angles_loop, values_loop]))
    patch = mpatches.PathPatch(
        path,
        facecolor=cmap(0.55),
        edgecolor=cmap(0.85),
        linewidth=2,
        alpha=0.18,
        transform=ax.transData,
    )
    ax.add_patch(patch)
    ax.plot(angles_loop, values_loop, color=cmap(0.8), linewidth=2)
    ax.fill(angles_loop, values_loop, color=cmap(0.5), alpha=0.10)
    ax.set_xticks([])
    ax.set_yticklabels([])
    ax.set_title(title, pad=28, fontsize=14)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=200, bbox_inches="tight")

    if show_plot:
        plt.show()
    plt.close(fig)
    return support_scores
