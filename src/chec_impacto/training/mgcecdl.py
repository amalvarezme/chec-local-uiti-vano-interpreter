"""Piezas compartidas del M-GCECDL que el flujo MIL sigue usando.

Este modulo fue el entrenamiento del CLASIFICADOR MGCECDL, retirado junto con
`MGCECDLClassifier`: ningun camino del flujo actual lo cargaba, y su artefacto
(`mgcecdl_classifier_best.zip`) tampoco. Lo que el simulador y el informe cargan es
`mil_vano_ventana_v1.pt`, el modelo MIL de bolsas.

Lo que queda aqui NO es residuo: son las piezas que el MIL y el cuaderno 05 importan de
verdad -- las modalidades, la perdida de reconstruccion del grafo, la deteccion de
variables exogenas y el reductor de supervision por modalidad. Se conservan en su sitio
para no mover una firma que tres consumidores ya nombran.
"""

from __future__ import annotations

import math
import os
import random
import warnings
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from sklearn.preprocessing import MinMaxScaler
from torch import nn
from torch.nn import functional as F



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


