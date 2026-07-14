"""Training helpers for CHEC M-GCECDL classification workflows."""

from __future__ import annotations

import copy
import io
import json
import math
import os
import random
import warnings
import zipfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import joblib
import numpy as np
import optuna
import torch
from optuna.storages import JournalFileStorage, JournalStorage
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import MinMaxScaler
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, TensorDataset

from chec_impacto.models.mgcecdl import MGCECDLClassifier


_DEVICE_RESOLUTION_CACHE: dict[str, torch.device] = {}
_CLASSIFICATION_COMPONENT_KEYS = (
    "total_loss",
    "fused_loss",
    "modality_loss",
    "agreement_loss",
    "kl_loss",
    "entropy_loss",
    "regularization_loss",
    "reconstruction_loss",
    "mutual_information",
    "mutual_information_loss",
)
def latest_model_path(model_dir: str | Path, base_name: str, *, verbose: bool = False) -> Path:
    """Return the latest model artifact matching a base file name pattern."""
    model_dir = Path(model_dir)
    base_path = Path(base_name)
    candidates = sorted(model_dir.glob(f"{base_path.stem}*{base_path.suffix}"))
    if not candidates:
        raise FileNotFoundError(f"No encontrado: {base_name} en {model_dir}")
    selected = candidates[-1]
    if verbose and len(candidates) > 1:
        print(f"  {len(candidates)} versiones de {base_name}. Usando: {selected.name}")
    return selected


def checkpoint_path(base_path: str | Path, *, timestamp: str | None = None) -> Path:
    """Return a timestamped checkpoint path when the base path already exists."""
    base_path = Path(base_path)
    if not base_path.exists():
        return base_path
    if timestamp is None:
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    return base_path.parent / f"{base_path.stem}_{timestamp}{base_path.suffix}"


MGCECDL_CLIMATE_PREFIXES = frozenset(
    {
        "prep",
        "temp",
        "wind_gust_spd",
        "wind_spd",
        "clouds",
        "pres",
        "sp",
        "rh",
        "solar_rad",
    }
)
MGCECDL_EXOGENOUS_FEATURES = frozenset({"DDT", "NR_T"})
MGCECDL_TWO_MODALITY_DEFAULT_NAMES = ("climaticos", "estructurales")


def seed_mgcecdl(seed: int = 42, deterministic: bool = False) -> None:
    """Seed Python, NumPy and Torch for MGCECDL experiments."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    if deterministic:
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch.use_deterministic_algorithms(True, warn_only=True)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True


def _feature_base_name(feature: str) -> str:
    name = str(feature)
    prefix, separator, suffix = name.rpartition("_")
    if separator and suffix.isdigit() and prefix in MGCECDL_CLIMATE_PREFIXES:
        return prefix
    return name


def es_variable_exogena_mgcecdl(feature: str) -> bool:
    """Return True when a feature belongs to the exogenous/climatic MGCECDL block."""
    base_name = _feature_base_name(feature)
    return base_name in MGCECDL_CLIMATE_PREFIXES or base_name in MGCECDL_EXOGENOUS_FEATURES


def construir_modalidades_mgcecdl(
    features: Sequence[str],
    nombres_modalidades: tuple[str, str] = MGCECDL_TWO_MODALITY_DEFAULT_NAMES,
) -> dict[str, list[int]]:
    """Build the two MGCECDL training modalities: climatic/exogenous and structural/endogenous."""
    if len(nombres_modalidades) != 2:
        raise ValueError("nombres_modalidades debe contener exactamente dos nombres.")

    exogenous_name, endogenous_name = nombres_modalidades
    if exogenous_name == endogenous_name:
        raise ValueError("Los nombres de modalidad MGCECDL deben ser distintos.")

    modality_feature_indices = {
        exogenous_name: [],
        endogenous_name: [],
    }
    for index, feature in enumerate(features):
        if es_variable_exogena_mgcecdl(str(feature)):
            modality_feature_indices[exogenous_name].append(index)
        else:
            modality_feature_indices[endogenous_name].append(index)

    _validar_modalidades_entrenamiento_mgcecdl(
        modality_feature_indices,
        n_features=len(features),
    )
    return modality_feature_indices


def _validar_modalidades_entrenamiento_mgcecdl(
    modality_feature_indices: Mapping[str, Sequence[int]],
    n_features: int | None = None,
) -> None:
    if len(modality_feature_indices) != 2:
        raise ValueError(
            "MGCECDL para busqueda y entrenamiento debe recibir exactamente dos modos: "
            "climaticos/exogenos y estructurales/endogenos."
        )

    flattened_indices: list[int] = []
    empty_modalities: list[str] = []
    for modality_name, indices in modality_feature_indices.items():
        indices_list = [int(index) for index in indices]
        if not indices_list:
            empty_modalities.append(str(modality_name))
        flattened_indices.extend(indices_list)

    if empty_modalities:
        raise ValueError(
            "Cada modo MGCECDL de entrenamiento debe tener al menos una variable. "
            f"Modos vacios: {empty_modalities}"
        )
    if len(flattened_indices) != len(set(flattened_indices)):
        raise ValueError("Cada feature debe pertenecer a un solo modo MGCECDL.")
    if not flattened_indices:
        raise ValueError("MGCECDL requiere al menos una feature para entrenar.")
    if min(flattened_indices) < 0:
        raise ValueError("Los indices de features MGCECDL no pueden ser negativos.")

    expected_n_features = max(flattened_indices) + 1 if n_features is None else int(n_features)
    expected_indices = set(range(expected_n_features))
    actual_indices = set(flattened_indices)
    if actual_indices != expected_indices:
        missing = sorted(expected_indices - actual_indices)
        extra = sorted(actual_indices - expected_indices)
        raise ValueError(
            "Los modos MGCECDL deben cubrir todas las features exactamente una vez. "
            f"Faltantes: {missing}. Extra: {extra}."
        )


def guardar_modelo_mgcecdl(
    model: MGCECDLClassifier,
    output_path: str | Path,
    state_dict: Mapping[str, torch.Tensor] | None = None,
) -> Path:
    """Save an M-GCECDL model and its architecture metadata in a ZIP archive."""
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".zip":
        raise ValueError("La ruta del modelo MGCECDL debe terminar en .zip.")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(model, MGCECDLClassifier):
        model_type = "classification"
        n_classes = model.n_classes
    else:
        raise TypeError(f"Tipo de modelo MGCECDL no soportado: {type(model).__name__}")

    metadata = {
        "format_version": 1,
        "model_type": model_type,
        "modality_feature_indices": dict(model.modality_feature_indices),
        "hidden_dim": model.hidden_dim,
        "embed_dim": model.embed_dim,
        "dropout": model.dropout,
        "temperature": model.temperature,
        "n_classes": n_classes,
    }
    weights_buffer = io.BytesIO()
    torch.save(model.state_dict() if state_dict is None else state_dict, weights_buffer)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(metadata, indent=2))
        archive.writestr("model.pt", weights_buffer.getvalue())
    return output_path


def cargar_modelo_mgcecdl(
    input_path: str | Path,
    device: str | torch.device = "cpu",
) -> MGCECDLClassifier:
    """Restore an M-GCECDL model from a ZIP archive created by this module."""
    input_path = Path(input_path)
    with zipfile.ZipFile(input_path, "r") as archive:
        metadata = json.loads(archive.read("metadata.json"))
        weights = io.BytesIO(archive.read("model.pt"))

    common_args = {
        "modality_feature_indices": metadata["modality_feature_indices"],
        "hidden_dim": int(metadata["hidden_dim"]),
        "embed_dim": int(metadata["embed_dim"]),
        "dropout": float(metadata["dropout"]),
        "temperature": float(metadata["temperature"]),
    }
    if metadata["model_type"] != "classification":
        raise ValueError(
            "Este proyecto solo soporta modelos MGCECDL de clasificacion. "
            f"Tipo encontrado: {metadata['model_type']}"
        )
    model = MGCECDLClassifier(n_classes=int(metadata["n_classes"]), **common_args)

    resolved_device = _coerce_device(device)
    state_dict = torch.load(weights, map_location=resolved_device, weights_only=True)
    model.load_state_dict(state_dict)
    model.to(resolved_device)
    model.eval()
    return model


def _coerce_device(device: str | torch.device) -> torch.device:
    if isinstance(device, torch.device):
        return device
    return torch.device(device)


def _probe_cuda_device(device: torch.device) -> tuple[bool, str | None]:
    if device.type != "cuda":
        return True, None
    if not torch.cuda.is_available():
        return False, "CUDA is not available in this runtime."

    try:
        probe = torch.arange(4, device=device, dtype=torch.float32)
        _ = (probe + 1).sum().item()
        torch.cuda.synchronize(device)
    except Exception as exc:  # pragma: no cover - depends on runtime/GPU availability.
        return False, str(exc)

    return True, None


def resolve_training_device(preferred_device: str | torch.device = "auto") -> torch.device:
    """Resolve CUDA, MPS, or CPU and fall back when CUDA cannot execute kernels."""
    cache_key = str(preferred_device)
    cached_device = _DEVICE_RESOLUTION_CACHE.get(cache_key)
    if cached_device is not None:
        return cached_device

    if isinstance(preferred_device, str) and preferred_device == "auto":
        if torch.cuda.is_available():
            resolved_device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            resolved_device = torch.device("mps")
        else:
            resolved_device = torch.device("cpu")
    else:
        resolved_device = _coerce_device(preferred_device)

    is_usable, error_message = _probe_cuda_device(resolved_device)
    if not is_usable:
        warnings.warn(
            "Falling back to CPU because the requested CUDA device is unavailable "
            f"or failed a runtime probe. Requested device: {resolved_device}. "
            f"Original error: {error_message}",
            RuntimeWarning,
            stacklevel=2,
        )
        resolved_device = torch.device("cpu")

    _DEVICE_RESOLUTION_CACHE[cache_key] = resolved_device
    _DEVICE_RESOLUTION_CACHE[str(resolved_device)] = resolved_device
    return resolved_device


def _reduce_modality_supervision_loss(
    modality_loss_matrix: torch.Tensor,
    reliabilities: torch.Tensor,
    weight_by_reliability: bool,
) -> torch.Tensor:
    """Reduce per-modality supervision losses using reliability weights or an active-modality mean."""
    if weight_by_reliability:
        return (reliabilities * modality_loss_matrix).sum(dim=1).mean()

    active_modalities = (reliabilities > 0).to(dtype=modality_loss_matrix.dtype)
    active_counts = active_modalities.sum(dim=1).clamp(min=1.0)
    return ((active_modalities * modality_loss_matrix).sum(dim=1) / active_counts).mean()


def calcular_estadisticas_reconstruccion_mgcecdl(
    X_train: np.ndarray,
    epsilon: float = 1e-6,
) -> tuple[np.ndarray, np.ndarray]:
    """Calculate feature standardization statistics using training data only."""
    X_train = np.asarray(X_train, dtype=np.float32)
    feature_mean = X_train.mean(axis=0, dtype=np.float64).astype(np.float32)
    feature_std = X_train.std(axis=0, dtype=np.float64).astype(np.float32)
    feature_std = np.where(feature_std < epsilon, 1.0, feature_std).astype(np.float32)
    return feature_mean, feature_std


def _normalize_unit_interval(
    values: torch.Tensor,
    scale: float | torch.Tensor,
    epsilon: float = 1e-8,
) -> torch.Tensor:
    scale_tensor = torch.as_tensor(
        scale,
        dtype=values.dtype,
        device=values.device,
    ).clamp(min=epsilon)
    return (values / scale_tensor).clamp(min=0.0, max=1.0)


def _safe_log_count(
    count: int,
    reference: torch.Tensor,
    epsilon: float = 1e-8,
) -> torch.Tensor:
    return reference.new_tensor(math.log(max(int(count), 2))).clamp(min=epsilon)


def _rbf_kernel_from_variable_profiles(
    variable_profiles: torch.Tensor,
    sigma: float | torch.Tensor,
    normalize_by_profile_dim: bool = False,
    epsilon: float = 1e-8,
) -> torch.Tensor:
    if variable_profiles.ndim != 2:
        raise ValueError("variable_profiles must have shape (n_variables, profile_dim).")
    squared_norms = variable_profiles.pow(2).sum(dim=1, keepdim=True)
    squared_distances = (
        squared_norms + squared_norms.T - 2.0 * variable_profiles @ variable_profiles.T
    ).clamp(min=0.0)
    if normalize_by_profile_dim:
        squared_distances = squared_distances / max(variable_profiles.shape[1], 1)
    sigma_tensor = torch.as_tensor(
        sigma,
        dtype=variable_profiles.dtype,
        device=variable_profiles.device,
    ).clamp(min=epsilon)
    return torch.exp(-squared_distances / (2.0 * sigma_tensor.pow(2)))


def _median_graph_sigma(graph_profiles: torch.Tensor, epsilon: float = 1e-8) -> torch.Tensor:
    distances = torch.pdist(graph_profiles, p=2)
    positive_distances = distances[distances > epsilon]
    if positive_distances.numel() == 0:
        return graph_profiles.new_tensor(1.0)
    return positive_distances.median().clamp(min=epsilon)


def _renyi_quadratic_entropy(kernel: torch.Tensor, epsilon: float = 1e-8) -> torch.Tensor:
    normalized_kernel = kernel / kernel.diagonal().sum().clamp(min=epsilon)
    information_potential = normalized_kernel.pow(2).sum().clamp(min=epsilon)
    return -torch.log(information_potential)


def _renyi_mutual_information(
    reconstruction_kernel: torch.Tensor,
    graph_kernel: torch.Tensor,
    epsilon: float = 1e-8,
) -> torch.Tensor:
    joint_kernel = reconstruction_kernel * graph_kernel
    return (
        _renyi_quadratic_entropy(reconstruction_kernel, epsilon)
        + _renyi_quadratic_entropy(graph_kernel, epsilon)
        - _renyi_quadratic_entropy(joint_kernel, epsilon)
    )


class _MGCECDLGraphReconstructionLoss(nn.Module):
    def __init__(
        self,
        feature_mean: np.ndarray | torch.Tensor,
        feature_std: np.ndarray | torch.Tensor,
        adjacency_matrix: np.ndarray | torch.Tensor,
        rbf_sigma: float,
        lambda_reconstruction: float,
        lambda_mutual_information: float,
    ) -> None:
        super().__init__()
        feature_mean_tensor = torch.as_tensor(feature_mean, dtype=torch.float32).reshape(-1)
        feature_std_tensor = torch.as_tensor(feature_std, dtype=torch.float32).reshape(-1)
        adjacency_tensor = torch.as_tensor(adjacency_matrix, dtype=torch.float32)
        feature_count = feature_mean_tensor.numel()
        if feature_std_tensor.numel() != feature_count:
            raise ValueError("feature_mean and feature_std must have the same length.")
        if adjacency_tensor.shape != (feature_count, feature_count):
            raise ValueError(
                "adjacency_matrix must have shape (n_features, n_features)."
            )
        self.register_buffer("feature_mean", feature_mean_tensor)
        self.register_buffer("feature_std", feature_std_tensor.clamp(min=1e-6))
        self.register_buffer("adjacency_matrix", adjacency_tensor)
        graph_profiles = torch.cat((adjacency_tensor, adjacency_tensor.T), dim=1)
        graph_sigma = _median_graph_sigma(graph_profiles)
        graph_kernel = _rbf_kernel_from_variable_profiles(graph_profiles, graph_sigma)
        self.register_buffer("graph_kernel", graph_kernel)
        self.register_buffer("graph_sigma", graph_sigma.reshape(()))
        self.register_buffer(
            "log_feature_count",
            torch.tensor(math.log(max(feature_count, 2)), dtype=torch.float32),
        )
        self.rbf_sigma = float(rbf_sigma)
        self.lambda_reconstruction = float(lambda_reconstruction)
        self.lambda_mutual_information = float(lambda_mutual_information)

    def _compute_graph_reconstruction_components(
        self,
        model_output: Mapping[str, torch.Tensor | list[torch.Tensor] | tuple[str, ...]],
        inputs: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        reconstructed_features = model_output["reconstructed_features"]
        standardized_inputs = (inputs - self.feature_mean) / self.feature_std
        reconstruction_loss_raw = F.mse_loss(
            reconstructed_features,
            standardized_inputs,
            reduction="mean",
        )
        reconstruction_loss = reconstruction_loss_raw.clamp(min=0.0, max=1.0)
        variable_profiles = reconstructed_features.T
        reconstruction_kernel = _rbf_kernel_from_variable_profiles(
            variable_profiles,
            self.rbf_sigma,
            normalize_by_profile_dim=True,
        )
        mutual_information = _renyi_mutual_information(
            reconstruction_kernel,
            self.graph_kernel,
        )
        mutual_information_normalized = (
            mutual_information / self.log_feature_count.clamp(min=1e-8)
        ).clamp(min=0.0, max=1.0)
        mutual_information_loss = 1.0 - mutual_information_normalized
        return {
            "reconstruction_loss": reconstruction_loss,
            "reconstruction_loss_raw": reconstruction_loss_raw,
            "mutual_information": mutual_information,
            "mutual_information_normalized": mutual_information_normalized,
            "mutual_information_loss": mutual_information_loss,
        }


def _initialize_running_metrics(keys: tuple[str, ...]) -> dict[str, float]:
    return {key: 0.0 for key in keys}


def _build_mgcecdl_optimizer(
    model: nn.Module,
    optimizer_type: str,
    learning_rate: float,
    momentum: float,
    weight_decay: float,
) -> torch.optim.Optimizer:
    optimizer_type = optimizer_type.lower()
    if optimizer_type == "adam":
        return torch.optim.Adam(
            model.parameters(),
            lr=float(min(max(learning_rate, 1e-4), 3e-3)),
            weight_decay=float(weight_decay),
        )
    if optimizer_type == "adamw":
        return torch.optim.AdamW(
            model.parameters(),
            lr=float(min(max(learning_rate, 1e-4), 3e-3)),
            weight_decay=float(weight_decay),
        )
    if optimizer_type == "sgd":
        return torch.optim.SGD(
            model.parameters(),
            lr=float(min(max(learning_rate, 1e-3), 1e-1)),
            momentum=float(momentum),
            weight_decay=float(weight_decay),
        )
    if optimizer_type == "rmsprop":
        return torch.optim.RMSprop(
            model.parameters(),
            lr=float(min(max(learning_rate, 1e-4), 3e-3)),
            momentum=float(momentum),
            weight_decay=float(weight_decay),
        )
    raise ValueError(f"Optimizador MGCECDL no soportado: {optimizer_type}")


class GCELoss(nn.Module):
    """Generalized cross-entropy loss applied sample-wise to class probabilities."""

    def __init__(self, q: float = 0.7) -> None:
        super().__init__()
        if q <= 0:
            raise ValueError("q must be strictly positive for generalized cross-entropy.")
        self.q = float(q)

    def forward(self, probabilities: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        labels = labels.reshape(-1).long()
        p = torch.gather(probabilities.clamp(min=1e-8), 1, labels.unsqueeze(1)).squeeze(1)
        return (1.0 - torch.pow(p, self.q)) / self.q


def _classification_gjs_divergence(
    modality_probs: torch.Tensor,
    reliabilities: torch.Tensor,
) -> torch.Tensor:
    """Compute a GJS-style consensus penalty over modality class probabilities."""
    mixed_probs = torch.sum(reliabilities.unsqueeze(-1) * modality_probs, dim=1)
    entropy_mix = -torch.sum(mixed_probs * torch.log(mixed_probs.clamp(min=1e-8)), dim=1)
    modality_entropies = -torch.sum(
        modality_probs * torch.log(modality_probs.clamp(min=1e-8)),
        dim=2,
    )
    weighted_entropy = torch.sum(reliabilities * modality_entropies, dim=1)
    return (entropy_mix - weighted_entropy).mean()


class MGCECDLClassificationLoss(_MGCECDLGraphReconstructionLoss):
    """Fused classification loss with independently weighted auxiliary objectives."""

    def __init__(
        self,
        q: float = 0.7,
        q_d: float = 0.5,
        gamma_sup: float = 0.20,
        gamma_agr: float = 0.10,
        gamma_reg: float = 0.01,
        tau: float = 0.1,
        alpha: float = 0.5,
        weight_modality_loss_by_reliability: bool = True,
        feature_mean: np.ndarray | torch.Tensor | None = None,
        feature_std: np.ndarray | torch.Tensor | None = None,
        adjacency_matrix: np.ndarray | torch.Tensor | None = None,
        rbf_sigma: float = 1.0,
        lambda_reconstruction: float = 0.01,
        lambda_mutual_information: float = 0.01,
    ) -> None:
        if feature_mean is None or feature_std is None or adjacency_matrix is None:
            raise ValueError(
                "feature_mean, feature_std, and adjacency_matrix are required."
            )
        super().__init__(
            feature_mean=feature_mean,
            feature_std=feature_std,
            adjacency_matrix=adjacency_matrix,
            rbf_sigma=rbf_sigma,
            lambda_reconstruction=lambda_reconstruction,
            lambda_mutual_information=lambda_mutual_information,
        )
        self.fused_gce = GCELoss(q=q)
        self.modality_gce = GCELoss(q=q_d)
        self.q = float(q)
        self.q_d = float(q_d)
        self.gamma_sup = float(gamma_sup)
        self.gamma_agr = float(gamma_agr)
        self.gamma_reg = float(gamma_reg)
        self.tau = float(tau)
        self.alpha = float(alpha)
        self.weight_modality_loss_by_reliability = bool(weight_modality_loss_by_reliability)

    def compute_components(
        self,
        model_output: Mapping[str, torch.Tensor | list[torch.Tensor] | tuple[str, ...]],
        targets: torch.Tensor,
        inputs: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        fused_probs = model_output["fused_probs"]
        modality_probs = model_output["modality_probs"]
        reliabilities = model_output["reliabilities"]
        targets = targets.reshape(-1).long()
        n_classes = fused_probs.size(1)
        n_modalities = reliabilities.size(1)
        class_log_scale = _safe_log_count(n_classes, fused_probs)
        modality_log_scale = _safe_log_count(n_modalities, reliabilities)

        fused_loss_raw = self.fused_gce(fused_probs, targets).mean()
        fused_loss = (self.q * fused_loss_raw).clamp(min=0.0, max=1.0)

        modality_loss_terms: list[torch.Tensor] = []
        entropy_terms: list[torch.Tensor] = []
        for modality_index in range(modality_probs.shape[1]):
            probs = modality_probs[:, modality_index, :]
            modality_gce = self.modality_gce(probs, targets)
            modality_loss_terms.append(modality_gce)

            entropy = -torch.sum(probs * torch.log(probs.clamp(min=1e-8)), dim=1)
            entropy_terms.append((reliabilities[:, modality_index] * entropy).mean())

        modality_loss_matrix = torch.stack(modality_loss_terms, dim=1)
        modality_loss_raw = _reduce_modality_supervision_loss(
            modality_loss_matrix,
            reliabilities,
            weight_by_reliability=self.weight_modality_loss_by_reliability,
        )
        modality_loss = (self.q_d * modality_loss_raw).clamp(min=0.0, max=1.0)
        agreement_loss_raw = _classification_gjs_divergence(modality_probs, reliabilities)
        agreement_loss = _normalize_unit_interval(agreement_loss_raw, class_log_scale)

        uniform_prior = torch.full_like(reliabilities, 1.0 / reliabilities.size(1))
        kl_loss_raw = F.kl_div(
            torch.log(reliabilities.clamp(min=1e-8)),
            uniform_prior,
            reduction="batchmean",
        )
        kl_loss = _normalize_unit_interval(kl_loss_raw, modality_log_scale)
        entropy_loss_raw = torch.stack(entropy_terms).sum()
        entropy_loss = _normalize_unit_interval(entropy_loss_raw, class_log_scale)
        regularization_denominator = max(self.tau + self.alpha, 1e-8)
        regularization_loss = (
            self.tau * kl_loss + self.alpha * entropy_loss
        ) / regularization_denominator
        graph_components = self._compute_graph_reconstruction_components(model_output, inputs)

        total_loss = (
            fused_loss
            + self.gamma_sup * modality_loss
            + self.gamma_agr * agreement_loss
            + self.gamma_reg * regularization_loss
            + self.lambda_reconstruction * graph_components["reconstruction_loss"]
            + self.lambda_mutual_information * graph_components["mutual_information_loss"]
        )
        return {
            "total_loss": total_loss,
            "fused_loss": fused_loss,
            "fused_loss_raw": fused_loss_raw,
            "modality_loss": modality_loss,
            "modality_loss_raw": modality_loss_raw,
            "agreement_loss": agreement_loss,
            "agreement_loss_raw": agreement_loss_raw,
            "kl_loss": kl_loss,
            "kl_loss_raw": kl_loss_raw,
            "entropy_loss": entropy_loss,
            "entropy_loss_raw": entropy_loss_raw,
            "regularization_loss": regularization_loss,
            **graph_components,
        }

    def forward(
        self,
        model_output: Mapping[str, torch.Tensor | list[torch.Tensor] | tuple[str, ...]],
        targets: torch.Tensor,
        inputs: torch.Tensor,
    ) -> torch.Tensor:
        return self.compute_components(model_output, targets, inputs)["total_loss"]


def compute_classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray | None = None,
) -> dict[str, float]:
    """Compute multiclass classification metrics on numpy arrays."""
    y_true = np.asarray(y_true).reshape(-1)
    y_pred = np.asarray(y_pred).reshape(-1)

    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "macro_precision": float(
            precision_score(y_true, y_pred, average="macro", zero_division=0)
        ),
        "macro_recall": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
    }

    if y_proba is not None:
        y_proba = np.asarray(y_proba)
        try:
            if y_proba.shape[1] == 2:
                auc = roc_auc_score(y_true, y_proba[:, 1])
            else:
                auc = roc_auc_score(y_true, y_proba, multi_class="ovr", average="macro")
            metrics["macro_auc"] = float(auc)
        except ValueError:
            metrics["macro_auc"] = float("nan")
    else:
        metrics["macro_auc"] = float("nan")

    return metrics


def _build_dataset(
    X: np.ndarray,
    y: np.ndarray,
    target_dtype: torch.dtype,
    modality_masks: np.ndarray | None = None,
) -> TensorDataset:
    tensors: list[torch.Tensor] = [
        torch.tensor(X, dtype=torch.float32),
        torch.tensor(y, dtype=target_dtype),
    ]
    if modality_masks is not None:
        tensors.append(torch.tensor(modality_masks, dtype=torch.float32))
    return TensorDataset(*tensors)


def _build_dataloader_generator(seed: int | None) -> torch.Generator | None:
    if seed is None:
        return None
    generator = torch.Generator()
    generator.manual_seed(int(seed))
    return generator


def create_classification_dataloaders(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    batch_size: int,
    train_modality_masks: np.ndarray | None = None,
    valid_modality_masks: np.ndarray | None = None,
    shuffle_seed: int | None = None,
) -> tuple[DataLoader, DataLoader]:
    """Create train and validation dataloaders for classification arrays."""
    train_dataset = _build_dataset(
        X_train,
        y_train,
        target_dtype=torch.long,
        modality_masks=train_modality_masks,
    )
    valid_dataset = _build_dataset(
        X_valid,
        y_valid,
        target_dtype=torch.long,
        modality_masks=valid_modality_masks,
    )
    generator = _build_dataloader_generator(shuffle_seed)
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        generator=generator,
    )
    valid_loader = DataLoader(valid_dataset, batch_size=batch_size, shuffle=False)
    return train_loader, valid_loader


def escalar_features_minmax_mgcecdl(
    splits: Mapping[str, Any],
    feature_range: tuple[float, float] = (0.0, 1.0),
) -> dict[str, Any]:
    """Fit MinMax on X_train and transform MGCECDL feature splits without touching y."""
    required_keys = {"X_train", "X_valid"}
    missing_keys = required_keys - set(splits)
    if missing_keys:
        raise ValueError(
            "Faltan splits de features para escalar MGCECDL: "
            f"{sorted(missing_keys)}"
        )

    scaler = MinMaxScaler(feature_range=feature_range)
    scaled_splits = dict(splits)
    scaled_splits["X_train"] = scaler.fit_transform(
        np.asarray(splits["X_train"], dtype=np.float32)
    ).astype(np.float32)
    scaled_splits["X_valid"] = scaler.transform(
        np.asarray(splits["X_valid"], dtype=np.float32)
    ).astype(np.float32)

    if "X_test" in splits:
        scaled_splits["X_test"] = scaler.transform(
            np.asarray(splits["X_test"], dtype=np.float32)
        ).astype(np.float32)

    scaled_splits["feature_scaler"] = scaler
    return scaled_splits


def _unpack_batch(
    batch: tuple[torch.Tensor, ...],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor | None]:
    if len(batch) == 2:
        X_batch, y_batch = batch
        return X_batch, y_batch, None
    if len(batch) == 3:
        X_batch, y_batch, modality_masks = batch
        return X_batch, y_batch, modality_masks
    raise ValueError(f"Unsupported batch format with {len(batch)} tensors.")


def _train_classification_one_epoch(
    model: MGCECDLClassifier,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    loss_fn: MGCECDLClassificationLoss,
    device: str | torch.device,
) -> dict[str, float]:
    """Train the classification model for one epoch and report mean loss components."""
    device = _coerce_device(device)
    model.train()
    loss_fn = loss_fn.to(device)
    running = _initialize_running_metrics(_CLASSIFICATION_COMPONENT_KEYS)

    for batch in loader:
        X_batch, y_batch, modality_masks = _unpack_batch(batch)
        X_batch = X_batch.to(device)
        y_batch = y_batch.to(device).reshape(-1).long()
        modality_masks = None if modality_masks is None else modality_masks.to(device)

        optimizer.zero_grad()
        outputs = model(X_batch, modality_masks=modality_masks)
        components = loss_fn.compute_components(outputs, y_batch, X_batch)
        components["total_loss"].backward()
        optimizer.step()

        for key in running:
            running[key] += float(components[key].detach().cpu())

    batch_count = max(len(loader), 1)
    return {key: value / batch_count for key, value in running.items()}


def evaluate_classification_model(
    model: MGCECDLClassifier,
    loader: DataLoader,
    loss_fn: MGCECDLClassificationLoss,
    device: str | torch.device,
) -> dict[str, Any]:
    """Evaluate the classification model and report metrics plus modality outputs."""
    device = _coerce_device(device)
    model.eval()
    loss_fn = loss_fn.to(device)
    running = _initialize_running_metrics(_CLASSIFICATION_COMPONENT_KEYS)
    all_probabilities: list[np.ndarray] = []
    all_predictions: list[np.ndarray] = []
    all_targets: list[np.ndarray] = []
    all_modality_probs: list[np.ndarray] = []
    all_modality_logits: list[np.ndarray] = []
    all_reliabilities: list[np.ndarray] = []
    all_fused_log_probs: list[np.ndarray] = []

    with torch.no_grad():
        for batch in loader:
            X_batch, y_batch, modality_masks = _unpack_batch(batch)
            X_batch = X_batch.to(device)
            y_batch = y_batch.to(device).reshape(-1).long()
            modality_masks = None if modality_masks is None else modality_masks.to(device)

            outputs = model(X_batch, modality_masks=modality_masks)
            components = loss_fn.compute_components(outputs, y_batch, X_batch)
            for key in running:
                running[key] += float(components[key].detach().cpu())

            all_probabilities.append(outputs["fused_probs"].detach().cpu().numpy())
            all_predictions.append(outputs["predicted_classes"].detach().cpu().numpy())
            all_targets.append(y_batch.detach().cpu().numpy())
            all_modality_probs.append(outputs["modality_probs"].detach().cpu().numpy())
            all_modality_logits.append(outputs["modality_logits"].detach().cpu().numpy())
            all_reliabilities.append(outputs["reliabilities"].detach().cpu().numpy())
            all_fused_log_probs.append(outputs["fused_log_probs"].detach().cpu().numpy())

    probabilities = np.vstack(all_probabilities)
    predictions = np.concatenate(all_predictions)
    targets = np.concatenate(all_targets)
    modality_probs = np.vstack(all_modality_probs)
    modality_logits = np.vstack(all_modality_logits)
    reliabilities = np.vstack(all_reliabilities)
    fused_log_probs = np.vstack(all_fused_log_probs)

    component_means = {
        key: value / max(len(loader), 1)
        for key, value in running.items()
    }
    metrics = compute_classification_metrics(targets, predictions, probabilities)
    metrics.update(
        {
            "loss": component_means["total_loss"],
            **component_means,
            "probabilities": probabilities,
            "predictions": predictions,
            "targets": targets,
            "modality_probs": modality_probs,
            "modality_logits": modality_logits,
            "reliabilities": reliabilities,
            "fused_log_probs": fused_log_probs,
        }
    )
    return metrics


def predict_classification(
    model: MGCECDLClassifier,
    X: np.ndarray,
    device: str | torch.device,
    batch_size: int = 1024,
) -> dict[str, np.ndarray | tuple[str, ...]]:
    """Predict class probabilities, classes, and modality outputs for numpy inputs."""
    device = resolve_training_device(device)
    model = model.to(device)
    dataset = TensorDataset(torch.tensor(X, dtype=torch.float32))
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    model.eval()
    fused_probs: list[np.ndarray] = []
    fused_log_probs: list[np.ndarray] = []
    predicted_classes: list[np.ndarray] = []
    modality_probs: list[np.ndarray] = []
    modality_logits: list[np.ndarray] = []
    reliabilities: list[np.ndarray] = []

    with torch.no_grad():
        for (X_batch,) in loader:
            X_batch = X_batch.to(device)
            outputs = model(X_batch)
            fused_probs.append(outputs["fused_probs"].detach().cpu().numpy())
            fused_log_probs.append(outputs["fused_log_probs"].detach().cpu().numpy())
            predicted_classes.append(outputs["predicted_classes"].detach().cpu().numpy())
            modality_probs.append(outputs["modality_probs"].detach().cpu().numpy())
            modality_logits.append(outputs["modality_logits"].detach().cpu().numpy())
            reliabilities.append(outputs["reliabilities"].detach().cpu().numpy())

    return {
        "fused_probs": np.vstack(fused_probs),
        "fused_log_probs": np.vstack(fused_log_probs),
        "predicted_classes": np.concatenate(predicted_classes),
        "modality_probs": np.vstack(modality_probs),
        "modality_logits": np.vstack(modality_logits),
        "reliabilities": np.vstack(reliabilities),
        "modality_names": outputs["modality_names"],
    }


def train_mgcecdl_classifier(
    model: MGCECDLClassifier,
    train_loader: DataLoader,
    valid_loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    loss_fn: MGCECDLClassificationLoss,
    device: str | torch.device,
    max_epochs: int = 100,
    patience: int = 20,
    checkpoint_path: str | Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Train the classification model with early stopping on validation accuracy."""
    _validar_modalidades_entrenamiento_mgcecdl(model.modality_feature_indices)
    device = resolve_training_device(device)
    best_metric = float("-inf")
    best_epoch = -1
    best_state: dict[str, torch.Tensor] | None = None
    epochs_without_improvement = 0
    history: list[dict[str, float]] = []

    checkpoint_path = None if checkpoint_path is None else Path(checkpoint_path)
    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(max_epochs):
        train_metrics = _train_classification_one_epoch(
            model,
            train_loader,
            optimizer,
            loss_fn,
            device,
        )
        valid_metrics = evaluate_classification_model(model, valid_loader, loss_fn, device)

        epoch_summary = {
            "epoch": float(epoch + 1),
            "train_loss": train_metrics["total_loss"],
            "valid_loss": valid_metrics["loss"],
            "valid_accuracy": valid_metrics["accuracy"],
            "valid_balanced_accuracy": valid_metrics["balanced_accuracy"],
            "valid_macro_f1": valid_metrics["macro_f1"],
            "valid_macro_auc": valid_metrics["macro_auc"],
        }
        epoch_summary.update(
            {f"train_{key}": train_metrics[key] for key in _CLASSIFICATION_COMPONENT_KEYS}
        )
        epoch_summary.update(
            {f"valid_{key}": valid_metrics[key] for key in _CLASSIFICATION_COMPONENT_KEYS}
        )
        history.append(epoch_summary)

        if verbose:
            best_so_far = max(best_metric, valid_metrics["accuracy"])
            best_epoch_so_far = epoch + 1 if valid_metrics["accuracy"] > best_metric else best_epoch
            print(
                f"Clasificacion | Epoch {epoch + 1:03d}/{max_epochs:03d} | "
                f"train_loss={train_metrics['total_loss']:.6f} | "
                f"valid_loss={valid_metrics['loss']:.6f} | "
                f"accuracy={valid_metrics['accuracy']:.6f} | "
                f"balanced_accuracy={valid_metrics['balanced_accuracy']:.6f} | "
                f"macro_f1={valid_metrics['macro_f1']:.6f} | "
                f"best_accuracy={best_so_far:.6f}@{best_epoch_so_far}",
                flush=True,
            )

        if valid_metrics["accuracy"] > best_metric:
            best_metric = valid_metrics["accuracy"]
            best_epoch = epoch + 1
            best_state = copy.deepcopy(model.state_dict())
            epochs_without_improvement = 0
            if checkpoint_path is not None:
                guardar_modelo_mgcecdl(model, checkpoint_path, best_state)
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                break

    if best_state is None:
        best_state = copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)

    return {
        "history": history,
        "best_epoch": best_epoch,
        "best_metric": best_metric,
        "checkpoint_path": str(checkpoint_path) if checkpoint_path is not None else None,
    }


def _build_classification_model_from_params(
    params: Mapping[str, float | int | bool],
    modality_feature_indices: Mapping[str, list[int]],
    n_classes: int,
) -> MGCECDLClassifier:
    return MGCECDLClassifier(
        modality_feature_indices=modality_feature_indices,
        n_classes=n_classes,
        hidden_dim=int(params["hidden_dim"]),
        embed_dim=int(params["embed_dim"]),
        dropout=float(params["dropout"]),
        temperature=float(params["temperature"]),
    )


def crear_objective_clasificacion_mgcecdl(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    modality_feature_indices: Mapping[str, list[int]],
    feature_mean: np.ndarray,
    feature_std: np.ndarray,
    adjacency_matrix: np.ndarray,
    n_classes: int,
    device: str | torch.device,
    max_epochs: int = 60,
    patience: int = 40,
    seed: int = 42,
    weight_modality_loss_by_reliability: bool = True,
) -> Callable[[optuna.trial.Trial], float]:
    """Create the Optuna objective for M-GCECDL classification."""
    _validar_modalidades_entrenamiento_mgcecdl(
        modality_feature_indices,
        n_features=X_train.shape[1],
    )
    device = resolve_training_device(device)

    def objective(trial: optuna.trial.Trial) -> float:
        seed_mgcecdl(seed)

        params = {
            "hidden_dim": trial.suggest_categorical("hidden_dim", [128, 192, 256]),
            "embed_dim": trial.suggest_categorical("embed_dim", [64, 96, 128]),
            "dropout": trial.suggest_float("dropout", 0.0, 0.25),
            "temperature": trial.suggest_float("temperature", 0.5, 2.0),
            "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-1, log=True),
            "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-4, log=True),
            "optimizer_type": trial.suggest_categorical(
                "optimizer_type", ["adam", "adamw", "sgd", "rmsprop"]
            ),
            "momentum": trial.suggest_float("momentum", 0.5, 0.95),
            "batch_size": trial.suggest_categorical("batch_size", [256, 512, 1024]),
            "q": trial.suggest_float("q", 0.35, 0.90),
            "q_d": trial.suggest_float("q_d", 0.35, 0.90),
            "gamma_sup": trial.suggest_float("gamma_sup", 1e-2, 1.0, log=True),
            "gamma_agr": trial.suggest_float("gamma_agr", 1e-2, 1.0, log=True),
            "gamma_reg": trial.suggest_float("gamma_reg", 1e-2, 1.0, log=True),
            "rbf_sigma": trial.suggest_float("rbf_sigma", 1e-2, 10.0, log=True),
            "lambda_reconstruction": trial.suggest_float(
                "lambda_reconstruction", 1e-2, 1.0, log=True
            ),
            "lambda_mutual_information": trial.suggest_float(
                "lambda_mutual_information", 1e-2, 1.0, log=True
            ),
        }

        model = _build_classification_model_from_params(
            params,
            modality_feature_indices,
            n_classes=n_classes,
        ).to(device)
        optimizer = _build_mgcecdl_optimizer(
            model=model,
            optimizer_type=str(params["optimizer_type"]),
            learning_rate=float(params["learning_rate"]),
            momentum=float(params["momentum"]),
            weight_decay=float(params["weight_decay"]),
        )
        loss_fn = MGCECDLClassificationLoss(
            q=float(params["q"]),
            q_d=float(params["q_d"]),
            gamma_sup=float(params["gamma_sup"]),
            gamma_agr=float(params["gamma_agr"]),
            gamma_reg=float(params["gamma_reg"]),
            tau=0.1,
            alpha=0.5,
            weight_modality_loss_by_reliability=weight_modality_loss_by_reliability,
            feature_mean=feature_mean,
            feature_std=feature_std,
            adjacency_matrix=adjacency_matrix,
            rbf_sigma=float(params["rbf_sigma"]),
            lambda_reconstruction=float(params["lambda_reconstruction"]),
            lambda_mutual_information=float(params["lambda_mutual_information"]),
        )
        train_loader, valid_loader = create_classification_dataloaders(
            X_train,
            y_train,
            X_valid,
            y_valid,
            batch_size=int(params["batch_size"]),
            shuffle_seed=seed,
        )
        result = train_mgcecdl_classifier(
            model=model,
            train_loader=train_loader,
            valid_loader=valid_loader,
            optimizer=optimizer,
            loss_fn=loss_fn,
            device=device,
            max_epochs=max_epochs,
            patience=patience,
            checkpoint_path=None,
        )
        return float(result["best_metric"])

    return objective


def run_optuna_study(
    objective: Callable[[optuna.trial.Trial], float],
    study_name: str,
    storage_path: str | Path,
    n_trials: int,
    seed: int = 42,
    direction: str = "minimize",
) -> optuna.Study:
    """Run or resume an Optuna study backed by an Optuna journal file."""
    storage_path = Path(storage_path)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage = JournalStorage(JournalFileStorage(str(storage_path)))

    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction=direction,
        sampler=optuna.samplers.GPSampler(seed=seed),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=3),
        load_if_exists=True,
    )
    study.optimize(objective, n_trials=n_trials)
    return study


def cargar_estudio_optuna_mgcecdl(
    storage_path: str | Path,
    modo_objetivo: str,
) -> optuna.Study:
    """Load an M-GCECDL study from its portable journal file."""
    storage_path = Path(storage_path)
    if not storage_path.exists():
        raise FileNotFoundError(f"No existe el journal Optuna MGCECDL: {storage_path}")

    if modo_objetivo.lower() != "clasificacion":
        raise ValueError("modo_objetivo debe ser 'clasificacion'.")

    storage = JournalStorage(JournalFileStorage(str(storage_path)))
    return optuna.load_study(
        study_name="mgcecdl_classification_weighted_losses",
        storage=storage,
    )


def guardar_estudio_optuna(study: optuna.Study, output_path: str | Path) -> Path:
    """Serialize an Optuna study object for notebook workflows."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(study, output_path)
    print(f"Objeto Optuna guardado en: {output_path}")
    return output_path


def buscar_estudio_optuna_mgcecdl(
    modo_objetivo: str,
    storage_path: str | Path,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    modality_feature_indices: Mapping[str, list[int]],
    feature_mean: np.ndarray,
    feature_std: np.ndarray,
    adjacency_matrix: np.ndarray,
    device: str | torch.device,
    n_trials: int = 20,
    max_epochs: int = 60,
    patience: int = 40,
    seed: int = 42,
    n_classes: int | None = None,
    weight_modality_loss_by_reliability: bool = True,
) -> optuna.Study:
    """Ejecuta la busqueda Optuna de MGCECDL para clasificacion."""
    _validar_modalidades_entrenamiento_mgcecdl(
        modality_feature_indices,
        n_features=X_train.shape[1],
    )
    modo_objetivo = modo_objetivo.lower()
    if modo_objetivo != "clasificacion":
        raise ValueError("modo_objetivo debe ser 'clasificacion'.")
    if n_classes is None:
        raise ValueError("n_classes es requerido para clasificacion.")
    objective = crear_objective_clasificacion_mgcecdl(
        X_train=X_train,
        y_train=y_train,
        X_valid=X_valid,
        y_valid=y_valid,
        modality_feature_indices=modality_feature_indices,
        feature_mean=feature_mean,
        feature_std=feature_std,
        adjacency_matrix=adjacency_matrix,
        n_classes=n_classes,
        device=device,
        max_epochs=max_epochs,
        patience=patience,
        seed=seed,
        weight_modality_loss_by_reliability=weight_modality_loss_by_reliability,
    )

    return run_optuna_study(
        objective=objective,
        study_name="mgcecdl_classification_weighted_losses",
        storage_path=storage_path,
        n_trials=n_trials,
        seed=seed,
        direction="maximize",
    )


def save_best_params(path: str | Path, params: Mapping[str, Any]) -> None:
    """Save best hyperparameters as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(params, handle, indent=2, sort_keys=True)


def load_best_params(path: str | Path) -> dict[str, Any]:
    """Load saved best hyperparameters from JSON."""
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)
