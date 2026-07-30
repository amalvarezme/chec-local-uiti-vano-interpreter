"""Modality-aware M-GCECDL models for CHEC impact modeling."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from scipy.stats import gaussian_kde
from torch import nn
from torch.nn import functional as F


class _FeatureAttentionGate(nn.Module):
    def __init__(self, input_dim: int) -> None:
        super().__init__()
        self.normalization = nn.LayerNorm(input_dim)
        self.scorer = nn.Linear(input_dim, input_dim)
        self.scale = float(input_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        scores = self.scorer(self.normalization(x))
        weights = F.softmax(scores, dim=1)
        return x * weights * self.scale


class _ModalityEncoder(nn.Module):
    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        embed_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.feature_attention = _FeatureAttentionGate(input_dim)
        self.network = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, embed_dim),
            nn.ReLU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.feature_attention(x)
        return self.network(x)


class _ModalityDecoder(nn.Module):
    def __init__(self, embed_dim: int, hidden_dim: int, output_dim: int, dropout: float) -> None:
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(embed_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        return self.network(embeddings)


class _BaseMGCECDL(nn.Module):
    def __init__(
        self,
        modality_feature_indices: Mapping[str, Sequence[int]],
        hidden_dim: int = 128,
        embed_dim: int = 64,
        dropout: float = 0.10,
        temperature: float = 1.0,
    ) -> None:
        super().__init__()

        if not modality_feature_indices:
            raise ValueError("At least one modality is required to build the model.")

        self.modality_names = tuple(modality_feature_indices.keys())
        self.modality_feature_indices = OrderedDict(
            (name, list(indices)) for name, indices in modality_feature_indices.items()
        )
        flattened_indices = [
            index for indices in self.modality_feature_indices.values() for index in indices
        ]
        if len(flattened_indices) != len(set(flattened_indices)):
            raise ValueError("Each input feature must belong to exactly one modality.")
        self.input_dim = max(flattened_indices) + 1
        if set(flattened_indices) != set(range(self.input_dim)):
            raise ValueError("Modality feature indices must cover every input feature exactly once.")
        self.hidden_dim = int(hidden_dim)
        self.embed_dim = int(embed_dim)
        self.dropout = float(dropout)
        self.temperature = float(temperature)

        self.modality_encoders = nn.ModuleList(
            _ModalityEncoder(
                len(indices),
                hidden_dim,
                embed_dim,
                dropout,
            )
            for indices in self.modality_feature_indices.values()
        )
        self.modality_reliability_heads = nn.ModuleList(
            nn.Linear(embed_dim, 1) for _ in self.modality_feature_indices
        )
        self.modality_decoders = nn.ModuleList(
            _ModalityDecoder(embed_dim, hidden_dim, len(indices), dropout)
            for indices in self.modality_feature_indices.values()
        )

    @property
    def n_modalities(self) -> int:
        return len(self.modality_names)

    def _encode_modalities(
        self,
        x: torch.Tensor,
    ) -> tuple[list[torch.Tensor], list[torch.Tensor]]:
        modality_embeddings: list[torch.Tensor] = []
        reliability_scores: list[torch.Tensor] = []

        for encoder, reliability_head, indices in zip(
            self.modality_encoders,
            self.modality_reliability_heads,
            self.modality_feature_indices.values(),
        ):
            modality_inputs = x[:, indices]
            embeddings = encoder(modality_inputs)
            modality_embeddings.append(embeddings)
            reliability_scores.append(reliability_head(embeddings).squeeze(-1))

        return modality_embeddings, reliability_scores

    def _decode_modalities(
        self,
        modality_embeddings: list[torch.Tensor],
    ) -> tuple[list[torch.Tensor], torch.Tensor]:
        modality_reconstructions = [
            decoder(embeddings)
            for decoder, embeddings in zip(self.modality_decoders, modality_embeddings)
        ]
        reconstructed_features = modality_embeddings[0].new_zeros(
            (modality_embeddings[0].shape[0], self.input_dim)
        )
        for reconstruction, indices in zip(
            modality_reconstructions,
            self.modality_feature_indices.values(),
        ):
            reconstructed_features[:, indices] = reconstruction
        return modality_reconstructions, reconstructed_features

    def _compute_reliabilities(
        self,
        reliability_scores: list[torch.Tensor],
        modality_masks: torch.Tensor | None = None,
    ) -> torch.Tensor:
        stacked_reliability_scores = torch.stack(reliability_scores, dim=1)
        if modality_masks is not None:
            if modality_masks.shape != stacked_reliability_scores.shape:
                raise ValueError(
                    "Expected modality masks with shape "
                    f"{stacked_reliability_scores.shape}, got {modality_masks.shape}."
                )
            stacked_reliability_scores = stacked_reliability_scores.masked_fill(
                modality_masks <= 0, -1e9
            )
        return F.softmax(stacked_reliability_scores / self.temperature, dim=1)


class MGCECDLClassifier(_BaseMGCECDL):
    """Classification adaptation of M-GCECDL using modality-specific class heads and reliabilities."""

    def __init__(
        self,
        modality_feature_indices: Mapping[str, Sequence[int]],
        n_classes: int,
        hidden_dim: int = 128,
        embed_dim: int = 64,
        dropout: float = 0.10,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            modality_feature_indices=modality_feature_indices,
            hidden_dim=hidden_dim,
            embed_dim=embed_dim,
            dropout=dropout,
            temperature=temperature,
        )
        if n_classes < 2:
            raise ValueError("Classification requires at least two classes.")
        self.n_classes = int(n_classes)
        self.modality_classifiers = nn.ModuleList(
            nn.Linear(embed_dim, self.n_classes) for _ in self.modality_feature_indices
        )

    def forward(
        self,
        x: torch.Tensor,
        modality_masks: torch.Tensor | None = None,
    ) -> dict[str, Any]:
        modality_embeddings, reliability_scores = self._encode_modalities(x)
        modality_reconstructions, reconstructed_features = self._decode_modalities(
            modality_embeddings
        )
        modality_logits: list[torch.Tensor] = []

        for embeddings, classifier_head in zip(modality_embeddings, self.modality_classifiers):
            modality_logits.append(classifier_head(embeddings))

        stacked_logits = torch.stack(modality_logits, dim=1)
        reliabilities = self._compute_reliabilities(reliability_scores, modality_masks)
        modality_probs = F.softmax(stacked_logits, dim=2)
        weighted_log_probs = torch.sum(
            reliabilities.unsqueeze(-1) * torch.log(modality_probs.clamp(min=1e-8)),
            dim=1,
        )
        fused_probs = F.softmax(weighted_log_probs, dim=1)
        confidence_contributions = reliabilities.unsqueeze(-1) * modality_probs

        return {
            "fused_probs": fused_probs,
            "fused_log_probs": weighted_log_probs,
            "predicted_classes": fused_probs.argmax(dim=1),
            "modality_probs": modality_probs,
            "modality_logits": stacked_logits,
            "confidence_contributions": confidence_contributions,
            "reliabilities": reliabilities,
            "embeddings": modality_embeddings,
            "modality_reconstructions": modality_reconstructions,
            "reconstructed_features": reconstructed_features,
            "modality_names": self.modality_names,
        }


class MGCECDLRegressor(_BaseMGCECDL):
    """Regression adaptation of M-GCECDL using modality-specific regression heads.

    Additive sibling of `MGCECDLClassifier`: it reuses the same modality
    encoders/decoders/reliability heads from `_BaseMGCECDL` and replaces the
    per-modality classification heads with per-modality scalar regression
    heads. Predictions are fused as a reliability-weighted average (instead
    of `MGCECDLClassifier`'s reliability-weighted mixture of softmax
    distributions), which is the natural regression analogue of the same
    "trust the more reliable modality more" mechanism.

    `MGCECDLClassifier`'s behavior is untouched -- this class does not
    modify `_BaseMGCECDL` in any way that changes the classifier's forward
    pass.
    """

    def __init__(
        self,
        modality_feature_indices: Mapping[str, Sequence[int]],
        hidden_dim: int = 128,
        embed_dim: int = 64,
        dropout: float = 0.10,
        temperature: float = 1.0,
    ) -> None:
        super().__init__(
            modality_feature_indices=modality_feature_indices,
            hidden_dim=hidden_dim,
            embed_dim=embed_dim,
            dropout=dropout,
            temperature=temperature,
        )
        self.modality_regressors = nn.ModuleList(
            nn.Linear(embed_dim, 1) for _ in self.modality_feature_indices
        )

    def forward(
        self,
        x: torch.Tensor,
        modality_masks: torch.Tensor | None = None,
    ) -> dict[str, Any]:
        modality_embeddings, reliability_scores = self._encode_modalities(x)
        modality_reconstructions, reconstructed_features = self._decode_modalities(
            modality_embeddings
        )
        modality_predictions: list[torch.Tensor] = []

        for embeddings, regressor_head in zip(modality_embeddings, self.modality_regressors):
            modality_predictions.append(regressor_head(embeddings).squeeze(-1))

        stacked_predictions = torch.stack(modality_predictions, dim=1)
        reliabilities = self._compute_reliabilities(reliability_scores, modality_masks)
        fused_prediction = torch.sum(reliabilities * stacked_predictions, dim=1)

        return {
            "fused_prediction": fused_prediction,
            "modality_predictions": stacked_predictions,
            "reliabilities": reliabilities,
            "embeddings": modality_embeddings,
            "modality_reconstructions": modality_reconstructions,
            "reconstructed_features": reconstructed_features,
            "modality_names": self.modality_names,
        }


class KernelDensityWeightedMSELoss(nn.Module):
    """MSE re-weighted by inverse target density, so sparse/tail target
    values (e.g. high-criticality vanos) do not get drowned out by dense
    mid-range mass the way plain MSE would drown them out.

    A Gaussian KDE is fit ONCE (via `from_targets`, typically on the
    training split's target values) on a fixed grid; at `forward` time,
    weights are interpolated from that grid (cheap, no O(batch x n_train)
    kernel evaluation per batch) and normalized to a per-batch mean of 1 so
    the overall loss scale stays comparable to plain MSE.

    Placed here (not in `chec_impacto.training.mgcecdl`, where
    `MGCECDLClassificationLoss` lives) because
    `src/chec_impacto/training/**` is under an explicit `Edit` deny in this
    repository's `.claude/settings.json`, protecting the production
    classification training module from edits -- this module is the
    nearest safe, additive home for new regression-only training logic.
    """

    def __init__(
        self,
        grid_values: np.ndarray | torch.Tensor,
        grid_density: np.ndarray | torch.Tensor,
        epsilon: float = 1e-6,
    ) -> None:
        super().__init__()
        grid_values_tensor = torch.as_tensor(grid_values, dtype=torch.float32).reshape(-1)
        grid_density_tensor = torch.as_tensor(grid_density, dtype=torch.float32).reshape(-1)
        if grid_values_tensor.numel() != grid_density_tensor.numel():
            raise ValueError("grid_values and grid_density must have the same length.")
        if grid_values_tensor.numel() < 2:
            raise ValueError("grid_values must contain at least two points.")

        sort_order = torch.argsort(grid_values_tensor)
        self.register_buffer("grid_values", grid_values_tensor[sort_order])
        self.register_buffer(
            "grid_density", grid_density_tensor[sort_order].clamp(min=epsilon)
        )
        self.epsilon = float(epsilon)

    @classmethod
    def from_targets(
        cls,
        targets: np.ndarray,
        n_grid: int = 512,
        bandwidth: float | str | None = None,
        epsilon: float = 1e-6,
    ) -> "KernelDensityWeightedMSELoss":
        """Fit a Gaussian KDE on `targets` and build the interpolation grid."""
        targets_np = np.asarray(targets, dtype=np.float64).reshape(-1)
        if targets_np.size < 2:
            raise ValueError("targets must contain at least two values to fit a KDE.")
        kde = gaussian_kde(targets_np, bw_method=bandwidth)
        grid_values = np.linspace(targets_np.min(), targets_np.max(), int(n_grid))
        grid_density = kde(grid_values)
        return cls(grid_values, grid_density, epsilon=epsilon)

    def compute_weights(self, targets: torch.Tensor) -> torch.Tensor:
        """Return per-element inverse-density weights (NOT batch-normalized)."""
        original_shape = targets.shape
        flat_targets = targets.reshape(-1).to(
            dtype=self.grid_values.dtype, device=self.grid_values.device
        )
        clamped = flat_targets.clamp(min=self.grid_values[0], max=self.grid_values[-1])

        indices = torch.searchsorted(self.grid_values, clamped)
        indices = indices.clamp(min=1, max=self.grid_values.numel() - 1)
        lower_idx = indices - 1
        upper_idx = indices

        lower_val = self.grid_values[lower_idx]
        upper_val = self.grid_values[upper_idx]
        lower_density = self.grid_density[lower_idx]
        upper_density = self.grid_density[upper_idx]

        span = (upper_val - lower_val).clamp(min=self.epsilon)
        interp_weight = ((clamped - lower_val) / span).clamp(0.0, 1.0)
        density = lower_density * (1.0 - interp_weight) + upper_density * interp_weight

        weights = 1.0 / density.clamp(min=self.epsilon)
        return weights.reshape(original_shape)

    def forward(self, predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        weights = self.compute_weights(targets)
        weights = weights / weights.mean().clamp(min=self.epsilon)
        squared_error = (predictions - targets).pow(2)
        return (weights * squared_error).mean()


def _elementwise_regression_loss(
    base_loss: str,
    predictions: torch.Tensor,
    targets: torch.Tensor,
    huber_delta: float = 1.0,
    kernel_loss_module: "KernelDensityWeightedMSELoss | None" = None,
) -> torch.Tensor:
    """Elementwise (unreduced) regression loss shared by `MGCECDLRegressionLoss`'s
    fused and per-modality supervision terms."""
    if base_loss == "mse":
        return (predictions - targets).pow(2)
    if base_loss == "huber":
        return F.huber_loss(predictions, targets, reduction="none", delta=huber_delta)
    if base_loss == "kernel_weighted_mse":
        if kernel_loss_module is None:
            raise ValueError(
                "base_loss='kernel_weighted_mse' requiere kernel_loss_module "
                "(KernelDensityWeightedMSELoss.from_targets(y_train))."
            )
        weights = kernel_loss_module.compute_weights(targets)
        return weights * (predictions - targets).pow(2)
    raise ValueError(
        f"base_loss no soportado: {base_loss!r}. Usa 'mse', 'huber' o 'kernel_weighted_mse'."
    )


class MGCECDLRegressionLoss(nn.Module):
    """Regression analogue of `MGCECDLClassificationLoss`, built for
    `MGCECDLRegressor`, with the SAME auxiliary loss structure:

    - `fused_loss`: supervised regression loss (configurable `base_loss`:
      `"mse"`, `"huber"`, or `"kernel_weighted_mse"`) on the fused
      prediction -- the regression analogue of classification's fused GCE
      term.
    - `modality_loss`: the same supervised regression loss applied
      per-modality and reduced with `_reduce_modality_supervision_loss`
      (imported, not reimplemented, from `chec_impacto.training.mgcecdl`)
      -- the exact same reliability-weighted reduction classification uses
      for its `gamma_sup` term.
    - `agreement_loss`: reliability-weighted squared deviation of each
      modality's prediction from the fused (consensus) prediction -- the
      continuous regression analogue of classification's GJS-divergence
      agreement term (both penalize a modality for disagreeing with the
      reliability-weighted consensus).
    - `kl_loss` / `regularization_loss`: KL divergence of the reliability
      distribution against a uniform prior -- identical computation to
      classification (imported, not reimplemented). Classification's
      `entropy_loss` is defined over categorical class probabilities and
      has no regression analogue, so it is deliberately dropped;
      `regularization_loss` here is `kl_loss` alone. This is the ONE
      documented, intentional asymmetry versus `MGCECDLClassificationLoss`
      -- everything else (fused/modality/agreement/kl/reconstruction/MI) is
      full parity.
    - `reconstruction_loss` / `mutual_information_loss`: computed by the
      SAME `_MGCECDLGraphReconstructionLoss` classification uses (held by
      composition, imported lazily -- see note below), same defaults
      (`rbf_sigma`, `lambda_reconstruction`, `lambda_mutual_information`).

    Unlike classification's GCE-based terms (naturally bounded because they
    operate on a probability simplex), regression residuals are not
    naturally bounded to `[0, 1]`, so -- unlike `MGCECDLClassificationLoss`
    -- `fused_loss`/`modality_loss`/`agreement_loss` are NOT clamped here;
    clamping them would silently equalize very different loss shapes (e.g.
    MSE vs. Huber on large residuals) and defeat the empirical loss-shape
    comparison this class exists to support.

    Implementation note on the import below: this class needs
    `_MGCECDLGraphReconstructionLoss`, `_reduce_modality_supervision_loss`,
    `_normalize_unit_interval`, and `_safe_log_count` from
    `chec_impacto.training.mgcecdl`, but `chec_impacto.training.mgcecdl`
    itself imports `MGCECDLClassifier` (and, transitively, this module) at
    ITS top level. A top-level import here would therefore be circular.
    The import is deferred to `__init__` instead: by the time any caller
    actually instantiates `MGCECDLRegressionLoss`, both modules have
    already finished loading, so the deferred import just fetches already-
    initialized objects from `sys.modules` -- no behavior change, no edit
    to `training/mgcecdl.py`, no circular import.
    """

    def __init__(
        self,
        base_loss: str = "mse",
        gamma_sup: float = 0.20,
        gamma_agr: float = 0.10,
        gamma_reg: float = 0.01,
        huber_delta: float = 1.0,
        kernel_loss_module: "KernelDensityWeightedMSELoss | None" = None,
        weight_modality_loss_by_reliability: bool = True,
        reconstruction_normalization: str = "clip",
        feature_mean: np.ndarray | torch.Tensor | None = None,
        feature_std: np.ndarray | torch.Tensor | None = None,
        adjacency_matrix: np.ndarray | torch.Tensor | None = None,
        rbf_sigma: float = 1.0,
        lambda_reconstruction: float = 0.01,
        lambda_mutual_information: float = 0.01,
    ) -> None:
        super().__init__()
        if base_loss not in {"mse", "huber", "kernel_weighted_mse"}:
            raise ValueError(
                f"base_loss no soportado: {base_loss!r}. Usa 'mse', 'huber' o 'kernel_weighted_mse'."
            )
        if base_loss == "kernel_weighted_mse" and kernel_loss_module is None:
            raise ValueError(
                "base_loss='kernel_weighted_mse' requiere kernel_loss_module "
                "(KernelDensityWeightedMSELoss.from_targets(y_train))."
            )
        if reconstruction_normalization not in {"clip", "soft"}:
            raise ValueError(
                f"reconstruction_normalization no soportado: {reconstruction_normalization!r}. "
                "Usa 'clip' o 'soft'."
            )
        if feature_mean is None or feature_std is None or adjacency_matrix is None:
            raise ValueError(
                "feature_mean, feature_std, and adjacency_matrix are required."
            )

        # Deferred import -- see the class docstring's implementation note.
        from chec_impacto.training.mgcecdl import (
            _MGCECDLGraphReconstructionLoss,
            _normalize_unit_interval,
            _reduce_modality_supervision_loss,
            _safe_log_count,
        )

        self.base_loss = base_loss
        self.huber_delta = float(huber_delta)
        self.kernel_loss_module = kernel_loss_module
        self.reconstruction_normalization = reconstruction_normalization
        self.gamma_sup = float(gamma_sup)
        self.gamma_agr = float(gamma_agr)
        self.gamma_reg = float(gamma_reg)
        self.weight_modality_loss_by_reliability = bool(weight_modality_loss_by_reliability)

        self._reduce_modality_supervision_loss = _reduce_modality_supervision_loss
        self._normalize_unit_interval = _normalize_unit_interval
        self._safe_log_count = _safe_log_count
        self._graph_reconstruction = _MGCECDLGraphReconstructionLoss(
            feature_mean=feature_mean,
            feature_std=feature_std,
            adjacency_matrix=adjacency_matrix,
            rbf_sigma=rbf_sigma,
            lambda_reconstruction=lambda_reconstruction,
            lambda_mutual_information=lambda_mutual_information,
        )

    def compute_components(
        self,
        model_output: Mapping[str, torch.Tensor | list[torch.Tensor] | tuple[str, ...]],
        targets: torch.Tensor,
        inputs: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        fused_prediction = model_output["fused_prediction"]
        modality_predictions = model_output["modality_predictions"]
        reliabilities = model_output["reliabilities"]
        targets = targets.reshape(-1).to(dtype=fused_prediction.dtype)
        n_modalities = reliabilities.size(1)
        modality_log_scale = self._safe_log_count(n_modalities, reliabilities)

        fused_loss = _elementwise_regression_loss(
            self.base_loss,
            fused_prediction,
            targets,
            huber_delta=self.huber_delta,
            kernel_loss_module=self.kernel_loss_module,
        ).mean()

        modality_targets = targets.unsqueeze(1).expand_as(modality_predictions)
        modality_loss_matrix = _elementwise_regression_loss(
            self.base_loss,
            modality_predictions,
            modality_targets,
            huber_delta=self.huber_delta,
            kernel_loss_module=self.kernel_loss_module,
        )
        modality_loss = self._reduce_modality_supervision_loss(
            modality_loss_matrix,
            reliabilities,
            weight_by_reliability=self.weight_modality_loss_by_reliability,
        )

        # Agreement: reliability-weighted squared deviation of each modality's
        # prediction from the fused (consensus) prediction -- see class docstring.
        deviations = (modality_predictions - fused_prediction.unsqueeze(1)).pow(2)
        agreement_loss = (reliabilities * deviations).sum(dim=1).mean()

        uniform_prior = torch.full_like(reliabilities, 1.0 / reliabilities.size(1))
        kl_loss_raw = F.kl_div(
            torch.log(reliabilities.clamp(min=1e-8)),
            uniform_prior,
            reduction="batchmean",
        )
        kl_loss = self._normalize_unit_interval(kl_loss_raw, modality_log_scale)
        regularization_loss = kl_loss  # entropy_loss has no regression analogue -- see docstring.

        graph_components = self._graph_reconstruction._compute_graph_reconstruction_components(
            model_output, inputs
        )

        if self.reconstruction_normalization == "soft":
            # `_MGCECDLGraphReconstructionLoss` normalizes reconstruction as
            # `clip(MSE, 0, 1)`. That is a DEAD FIXED POINT for regression: the inputs are
            # standardized, so an untrained decoder already sits at MSE ~= 1 (measured at
            # 1.3124 on the real dataset at initialization). Above the ceiling `clamp` has
            # exactly zero gradient, so the term can never be taught to come down -- it just
            # contributes a constant. A full run of 11_mgcecdl_regression_budget.ipynb spent
            # 60% of its loss value on this constant while the supervised term got 14%.
            #
            # `MSE / (1 + MSE)` keeps every property the clip was there for -- range [0, 1),
            # monotone increasing, 0 still means a perfect reconstruction, comparable scale
            # for Optuna -- but its derivative `1 / (1 + MSE)^2` is strictly positive
            # everywhere, so the term keeps teaching instead of saturating.
            #
            # Applied HERE and not in `_MGCECDLGraphReconstructionLoss` on purpose: that class
            # is shared with the production `MGCECDLClassificationLoss` and lives under an
            # explicit `Edit` deny (`src/chec_impacto/training/**`). Classification's terms are
            # naturally bounded on a probability simplex and do not suffer this saturation,
            # so the fix belongs to the regression path only.
            raw_reconstruction = graph_components["reconstruction_loss_raw"]
            graph_components["reconstruction_loss"] = raw_reconstruction / (
                1.0 + raw_reconstruction
            )

        total_loss = (
            fused_loss
            + self.gamma_sup * modality_loss
            + self.gamma_agr * agreement_loss
            + self.gamma_reg * regularization_loss
            + self._graph_reconstruction.lambda_reconstruction * graph_components["reconstruction_loss"]
            + self._graph_reconstruction.lambda_mutual_information
            * graph_components["mutual_information_loss"]
        )

        return {
            "total_loss": total_loss,
            "fused_loss": fused_loss,
            "modality_loss": modality_loss,
            "agreement_loss": agreement_loss,
            "kl_loss": kl_loss,
            "kl_loss_raw": kl_loss_raw,
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
