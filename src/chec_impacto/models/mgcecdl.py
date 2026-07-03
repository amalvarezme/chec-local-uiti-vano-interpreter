"""Modality-aware M-GCECDL models for CHEC impact modeling."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Mapping, Sequence

import torch
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
