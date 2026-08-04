"""Bag-level multiple-instance regressor over 01.4's vano x window bags.

Bags are `(CIRCUITO, FID_VANO, ventana)` cells (`chec_impacto.data.bags.BagIndex`);
instances are event rows. `MILBagRegressor` encodes each instance with the
EXISTING `MGCECDLRegressor._encode_modalities` (reused unchanged), pools
instances into a bag latent with cardinality-invariant `SegmentAttentionPool`,
decodes ONE per-bag edge gate over the fixed expert graph with the EXISTING
`PerSampleEdgeGateDecoder` (also reused unchanged), propagates the gated
adjacency back onto every instance of that bag, re-encodes through the SAME
base model, re-pools, and reads a single bag scalar
`p_bag ~= log1p(uiti_acumulado)`. See:
  - spec: `sdd/notebook-10-mil-vano-ventana/spec` (domain `mil-bag-model`)
  - design: `sdd/notebook-10-mil-vano-ventana/design` (D2, D3, D5)

`p` (instance feature count) and `E` (edge count) are ALWAYS derived at
runtime from the adjacency matrix / edge index the caller supplies -- this
module must never hardcode either. Obs #536 corrected an earlier design-time
estimate of both counts on the real dataset at the design-pinned 1.0%
COD_CAUSA collapse threshold; this module never encodes that measurement or
any other literal feature/edge count (see
`tests/test_mgcecdl_mil.py::test_no_forbidden_literal_counts_in_mil_module`).

`GraphGatedMGCECDLRegressor` (`models/mgcecdl_graph.py`) is deliberately NOT
reused for the propagation step: it decodes a gate from a PER-ROW latent and
materializes a dense `(B, p, p)` gated adjacency via `bmm`, which at instance
grain would mean a `(n_bags, p, p)` -- rather than `(n_inst, p, p)` -- tensor
per per-bag gate broadcast onto every instance; edge-wise `index_add` avoids
ever materializing a dense adjacency at all, `O(n_inst * E)` instead of
`O(n_inst * p^2)`.

`src/chec_impacto/training/**` is Edit-denied; `MILBagLoss` imports
`_MGCECDLGraphReconstructionLoss` from it lazily (deferred to `__init__`),
mirroring `MGCECDLRegressionLoss` (`models/mgcecdl.py:516-522`) and
`GatedSelfSupervisedLoss` (`models/mgcecdl_graph.py:291-304`).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

import numpy as np
import torch
from torch import nn

from chec_impacto.models.mgcecdl import KernelDensityWeightedMSELoss, MGCECDLRegressor
from chec_impacto.models.mgcecdl_graph import GraphEdgeIndex, PerSampleEdgeGateDecoder

_SUPPORTED_OPTIMIZERS = ("adam", "adamw")


class SegmentAttentionPool(nn.Module):
    """Normalized gated attention pooling over a CSR-style instance segment
    index (design D2, Ilse-style attention).

    `e_i = w . tanh(V z_i)`; `a = segment_softmax(e, instance_bag)`
    (max-subtracted per bag via `scatter_reduce(..., reduce="amax")` for
    numerical stability); `z_bag[b] = sum_{i in b} a_i * z_i` via
    `index_add`. This is cardinality-invariant BY CONSTRUCTION: duplicating
    every instance of a bag leaves every `e_i` unchanged (encoding is
    per-instance, and every encoder in this codebase uses LayerNorm, never
    BatchNorm, so an instance's encoding never depends on batch
    composition), so the segment-softmax denominator doubles, each of the
    two copies receives `a_i / 2`, and their weighted sum is unchanged.
    """

    def __init__(self, latent_dim: int, attn_dim: int = 64) -> None:
        super().__init__()
        self.score_projection = nn.Linear(latent_dim, attn_dim)
        self.score_head = nn.Linear(attn_dim, 1)

    def forward(
        self,
        z: torch.Tensor,
        instance_bag: torch.Tensor,
        n_bags: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        instance_bag = instance_bag.to(dtype=torch.long)
        scores = self.score_head(torch.tanh(self.score_projection(z))).squeeze(-1)  # (n_inst,)

        # Max-subtraction is a pure numerical-stability shim (does not change the
        # softmax value), so it is safe to compute outside autograd.
        with torch.no_grad():
            bag_max = scores.new_full((n_bags,), float("-inf"))
            bag_max = bag_max.scatter_reduce(
                0, instance_bag, scores, reduce="amax", include_self=True
            )
        shifted_scores = scores - bag_max[instance_bag]
        exp_scores = torch.exp(shifted_scores)

        bag_sum = scores.new_zeros(n_bags)
        bag_sum = bag_sum.index_add(0, instance_bag, exp_scores)
        attention = exp_scores / bag_sum[instance_bag].clamp(min=1e-12)

        z_bag = z.new_zeros((n_bags, z.shape[1]))
        z_bag = z_bag.index_add(0, instance_bag, attention.unsqueeze(-1) * z)
        return z_bag, attention


class MILBagRegressor(nn.Module):
    """Pool -> per-bag gate -> edge-wise propagate onto instances -> re-encode
    -> re-pool -> bag head (design D3).

    Reuses `base._encode_modalities`/`base.forward` and
    `PerSampleEdgeGateDecoder` UNCHANGED.

    `fusion` selects how the bag prediction is formed:

    - `"concat"` (default, preserves the originally measured arm): a single
      `Linear(latent_dim, 1)` over the concatenated pooled latent. Both
      modality ENCODERS feed it, but `base.modality_regressors` and
      `base.modality_reliability_heads` receive no gradient -- reliability
      fusion is inert. That was not a preference: `MGCECDLRegressor.forward`
      fuses at INSTANCE grain and the label here is per BAG, so its fused
      prediction had no target to answer to.
    - `"reliability"`: fusion moved to bag grain, where the label lives.
      `p_bag = sum_m r_m * p_m` with `p_m = base.modality_regressors[m]`
      and `r_m` a softmax over `base.modality_reliability_heads[m]`, both
      applied to the pooled per-modality embedding. Revives both head
      families with their existing weights and yields a per-bag modality
      attribution (`reliabilities`) that a per-circuit report can read
      directly.

    Under `"reliability"` there is no `self.head`: replacing one dead path
    with another would defeat the purpose.
    """

    def __init__(
        self,
        base: MGCECDLRegressor,
        adjacency: np.ndarray | torch.Tensor,
        edge_index: GraphEdgeIndex,
        alpha: float,
        attn_dim: int = 64,
        fusion: str = "concat",
    ) -> None:
        super().__init__()
        if fusion not in ("concat", "reliability"):
            raise ValueError(
                f"fusion must be 'concat' or 'reliability' (received: {fusion!r})."
            )
        adjacency_tensor = torch.as_tensor(adjacency, dtype=torch.float32)
        n_features = adjacency_tensor.shape[0]
        if adjacency_tensor.shape != (n_features, n_features):
            raise ValueError("adjacency must be square with shape (p, p).")
        if base.input_dim != n_features:
            raise ValueError(
                f"base.input_dim ({base.input_dim}) does not match the adjacency's feature "
                f"count ({n_features})."
            )

        self.base = base
        self.edge_index = edge_index
        self.alpha = float(alpha)

        self.register_buffer("adjacency", adjacency_tensor)
        edge_pairs = torch.as_tensor(edge_index.pairs, dtype=torch.long)
        self.register_buffer("edge_rows", edge_pairs[:, 0].contiguous())
        self.register_buffer("edge_cols", edge_pairs[:, 1].contiguous())
        edge_values = adjacency_tensor[self.edge_rows, self.edge_cols]

        # Same contradiction guard as `GraphGatedMGCECDLRegressor`
        # (`models/mgcecdl_graph.py:206-223`): the forward pass scales gates by
        # `adjacency[row, col]`, so a caller-supplied `edge_index.weights` that
        # disagrees with THIS adjacency would describe a graph the model never
        # actually used to any downstream reader of `edge_index`.
        declared_weights = torch.as_tensor(edge_index.weights, dtype=torch.float32)
        if declared_weights.shape != edge_values.shape or not torch.allclose(
            edge_values, declared_weights, atol=1e-5
        ):
            raise ValueError(
                "edge_index.weights contradicts the adjacency it indexes into: the forward "
                "pass would use adjacency[row, col] while any downstream reader would report "
                "edge_index.weights. Build the edge index from this same adjacency."
            )
        self.register_buffer("edge_values", edge_values)

        latent_dim = base.n_modalities * base.embed_dim
        self.fusion = fusion
        self.attention_pool = SegmentAttentionPool(latent_dim=latent_dim, attn_dim=attn_dim)
        self.gate_decoder = PerSampleEdgeGateDecoder(
            latent_dim=latent_dim, n_edges=edge_index.n_edges
        )
        # Under "reliability" the bag head IS `base.modality_regressors` +
        # `base.modality_reliability_heads`; creating an unused `self.head`
        # would just move the dead path instead of removing it.
        self.head = nn.Linear(latent_dim, 1) if fusion == "concat" else None

    def forward(
        self,
        x_inst: torch.Tensor,
        instance_bag: torch.Tensor,
        n_bags: int,
    ) -> dict[str, Any]:
        instance_bag = instance_bag.to(dtype=torch.long)

        # Pass 1: gate source only -- no decode, no reliability/prediction use.
        modality_embeddings_1, _reliability_scores_1 = self.base._encode_modalities(x_inst)
        z1 = torch.cat(modality_embeddings_1, dim=1)

        z_bag, attention = self.attention_pool(z1, instance_bag, n_bags)
        edge_gates = self.gate_decoder(z_bag)  # (n_bags, n_edges), strictly in (0, 2)

        gates_per_instance = edge_gates[instance_bag]  # (n_inst, n_edges)
        messages = (
            self.alpha
            * gates_per_instance
            * self.edge_values.unsqueeze(0)
            * x_inst[:, self.edge_rows]
        )
        # `index_add` (out-of-place, differentiable): accumulates `messages`
        # column-wise onto `x_inst`, only at `edge_cols` positions -- any
        # feature column absent from `edge_cols` (e.g. every degree-0
        # `COD_CAUSA_*` indicator) is therefore untouched, exactly.
        propagated_inputs = x_inst.index_add(1, self.edge_cols, messages)

        # Pass 2: SAME base module, full forward (encode + decode + heads).
        model_output_2 = self.base(propagated_inputs)
        reconstructed_features = model_output_2["reconstructed_features"]
        modality_embeddings_2 = model_output_2["embeddings"]
        z2 = torch.cat(modality_embeddings_2, dim=1)

        # SAME attention module (shared weights) re-pools the post-propagation latent.
        z_bag_2, attention_2 = self.attention_pool(z2, instance_bag, n_bags)

        salida: dict[str, Any] = {
            "edge_gates": edge_gates,
            "attention": attention,
            "attention_pass2": attention_2,
            "reconstructed_features": reconstructed_features,
            "propagated_inputs": propagated_inputs,
            "embeddings": modality_embeddings_2,
        }

        if self.fusion == "reliability":
            # Bag-grain reliability fusion. `z_bag_2` is a sum over instances of
            # concatenated per-modality embeddings weighted by a SINGLE attention
            # distribution, and pooling is linear in `z` for fixed `a`, so column
            # slice `m` of `z_bag_2` IS modality `m` pooled on its own -- no extra
            # pooling pass, and one interpretable "which instances matter" story
            # shared by both modalities. The per-modality split of the prediction
            # then lives entirely in the reliabilities.
            embed_dim = self.base.embed_dim
            bag_embeddings = [
                z_bag_2[:, i * embed_dim : (i + 1) * embed_dim]
                for i in range(self.base.n_modalities)
            ]
            modality_predictions = torch.stack(
                [
                    regressor(embedding).squeeze(-1)
                    for regressor, embedding in zip(
                        self.base.modality_regressors, bag_embeddings
                    )
                ],
                dim=1,
            )
            reliability_scores = [
                head(embedding).squeeze(-1)
                for head, embedding in zip(
                    self.base.modality_reliability_heads, bag_embeddings
                )
            ]
            reliabilities = self.base._compute_reliabilities(reliability_scores)
            salida["p_bag"] = torch.sum(reliabilities * modality_predictions, dim=1)
            salida["modality_predictions"] = modality_predictions
            salida["reliabilities"] = reliabilities
        else:
            salida["p_bag"] = self.head(z_bag_2).squeeze(-1)

        return salida


class MILBagLoss(nn.Module):
    """Bag-grain supervised loss + instance-grain reconstruction/MI + bag-grain
    gate deviation (design D5).

    `agreement_loss`/`kl_loss` are deliberately absent -- carrying
    `sdd/notebook-12-criticality-representation/design` D1's verdict
    verbatim: both terms' global minimum is reachable by zeroing exactly the
    heads `MILBagRegressor.forward` never routes gradient to in the first
    place, so they would regularize a dead path while still leaking
    unmotivated gradient into the shared encoder.

    That verdict is scoped to `fusion="concat"`. Under
    `fusion="reliability"` those heads are live and carry the bag
    prediction, so the "regularizes a dead path" argument no longer holds
    for that arm -- the terms stay out because nothing has measured them
    here, not because they are provably inert. `lambda_modality_supervised`
    is the term that arm actually needs; see `compute_components`.
    """

    def __init__(
        self,
        feature_mean: np.ndarray | torch.Tensor,
        feature_std: np.ndarray | torch.Tensor,
        adjacency_matrix: np.ndarray | torch.Tensor,
        kernel_loss: KernelDensityWeightedMSELoss,
        rbf_sigma: float = 1.0,
        lambda_supervised: float = 1.0,
        lambda_reconstruction: float = 0.01,
        lambda_mutual_information: float = 0.01,
        lambda_gate_deviation: float = 0.0,
        lambda_modality_supervised: float = 0.0,
        reconstruction_normalization: str = "soft",
    ) -> None:
        super().__init__()
        if reconstruction_normalization != "soft":
            raise ValueError(
                "reconstruction_normalization must be 'soft' for the MIL bag regressor "
                f"(received: {reconstruction_normalization!r}). 'clip' pins the "
                "reconstruction term at exactly 1.0 with zero gradient once the raw MSE "
                "exceeds 1 -- see models/mgcecdl.py:598-620 for the measured evidence."
            )
        if kernel_loss is None:
            raise ValueError(
                "kernel_loss is required and must already be fitted on the TRAINING FOLD's "
                "log1p(y) only (KernelDensityWeightedMSELoss.from_targets) -- fitting it on "
                "all folds would leak the held-out target distribution into the training "
                "objective (design D5)."
            )

        # Deferred import -- mirrors `MGCECDLRegressionLoss` (`models/mgcecdl.py:516-522`)
        # and `GatedSelfSupervisedLoss` (`models/mgcecdl_graph.py:291-304`): avoids a
        # `models` <-> `training` circular import.
        from chec_impacto.training.mgcecdl import _MGCECDLGraphReconstructionLoss

        self._graph_reconstruction = _MGCECDLGraphReconstructionLoss(
            feature_mean=feature_mean,
            feature_std=feature_std,
            adjacency_matrix=adjacency_matrix,
            rbf_sigma=rbf_sigma,
            lambda_reconstruction=lambda_reconstruction,
            lambda_mutual_information=lambda_mutual_information,
        )
        self.kernel_loss = kernel_loss
        self.reconstruction_normalization = reconstruction_normalization
        self.lambda_supervised = float(lambda_supervised)
        self.lambda_gate_deviation = float(lambda_gate_deviation)
        self.lambda_modality_supervised = float(lambda_modality_supervised)

    def compute_components(
        self,
        model_output: Mapping[str, torch.Tensor],
        inputs: torch.Tensor,
        y_bag: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        p_bag = model_output["p_bag"]
        targets = torch.log1p(y_bag.reshape(-1).to(dtype=p_bag.dtype))
        supervised_loss = self.kernel_loss(p_bag, targets)

        # `inputs` MUST be the ORIGINAL x_inst, never `model_output["propagated_inputs"]`
        # (design D5, carrying nb12's D2 verbatim): otherwise the gate controls its own
        # reconstruction target and can lower the loss by simplifying it rather than by
        # improving the representation.
        graph_components = self._graph_reconstruction._compute_graph_reconstruction_components(
            model_output, inputs
        )
        raw_reconstruction = graph_components["reconstruction_loss_raw"]
        soft_reconstruction = raw_reconstruction / (1.0 + raw_reconstruction)

        edge_gates = model_output["edge_gates"]
        gate_deviation_loss = self.lambda_gate_deviation * (edge_gates - 1.0).abs().mean()

        # Supervising each modality's own bag prediction is what keeps the
        # reliabilities READABLE. Without it, `r_m` and `p_m` co-adapt freely:
        # a modality can predict noise while its reliability collapses to zero
        # to compensate, and `r_m` stops meaning "how much this modality knows".
        # Absent under `fusion="concat"`, where there are no per-modality bag
        # predictions to supervise -- the term is inert, never an error.
        modality_predictions = model_output.get("modality_predictions")
        if self.lambda_modality_supervised > 0.0 and modality_predictions is not None:
            per_modality = torch.stack(
                [
                    self.kernel_loss(modality_predictions[:, m], targets)
                    for m in range(modality_predictions.shape[1])
                ]
            )
            modality_supervised_loss = self.lambda_modality_supervised * per_modality.mean()
        else:
            modality_supervised_loss = supervised_loss.new_zeros(())

        total_loss = (
            self.lambda_supervised * supervised_loss
            + self._graph_reconstruction.lambda_reconstruction * soft_reconstruction
            + self._graph_reconstruction.lambda_mutual_information
            * graph_components["mutual_information_loss"]
            + gate_deviation_loss
            + modality_supervised_loss
        )

        return {
            "total_loss": total_loss,
            "supervised_loss": supervised_loss,
            "modality_supervised_loss": modality_supervised_loss,
            "reconstruction_loss": soft_reconstruction,
            "reconstruction_loss_raw": raw_reconstruction,
            "mutual_information": graph_components["mutual_information"],
            "mutual_information_normalized": graph_components["mutual_information_normalized"],
            "mutual_information_loss": graph_components["mutual_information_loss"],
            "gate_deviation_loss": gate_deviation_loss,
        }

    def forward(
        self,
        model_output: Mapping[str, torch.Tensor],
        inputs: torch.Tensor,
        y_bag: torch.Tensor,
    ) -> torch.Tensor:
        return self.compute_components(model_output, inputs, y_bag)["total_loss"]


_TRACKED_HISTORY_KEYS = (
    "total_loss",
    "supervised_loss",
    "reconstruction_loss",
    "reconstruction_loss_raw",
    "mutual_information_loss",
    "mutual_information_normalized",
    "gate_deviation_loss",
    "modality_supervised_loss",
)


def _lote_de_instancias(bag_index: Any, bag_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Gather instance-row positions for `bag_ids` from a CSR `BagIndex`, plus
    a LOCAL bag id per instance (`0 .. len(bag_ids) - 1`)."""
    filas: list[np.ndarray] = []
    bolsa_local: list[np.ndarray] = []
    for indice_local, bag_id in enumerate(bag_ids):
        inicio = int(bag_index.offsets[bag_id])
        fin = int(bag_index.offsets[bag_id + 1])
        filas.append(np.arange(inicio, fin, dtype=np.int64))
        bolsa_local.append(np.full(fin - inicio, indice_local, dtype=np.int64))
    if not filas:
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    return np.concatenate(filas), np.concatenate(bolsa_local)


def _formatear_mmss(segundos: float) -> str:
    """Render a duration in `mm:ss`, rounded to the nearest whole second."""
    total_segundos = max(0, int(round(segundos)))
    minutos, restantes = divmod(total_segundos, 60)
    return f"{minutos:02d}:{restantes:02d}"


def entrenar_mil(
    model: MILBagRegressor,
    loss_fn: MILBagLoss,
    X_inst: np.ndarray | torch.Tensor,
    bag_index: Any,
    *,
    epochs: int,
    bag_batch_size: int = 256,
    lr: float = 1e-3,
    weight_decay: float = 1e-5,
    optimizer_name: str = "adamw",
    seed: int = 42,
    device: str | torch.device = "cpu",
    verbose: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fit `model` bag-supervised (D5) over a `BagIndex`'s CSR layout.

    `loss_fn.kernel_loss` must already be fitted on the TRAINING FOLD's
    `log1p(y)` only (fold hygiene, D5) -- this function never touches
    `loss_fn.kernel_loss`'s grid, and performs no fold splitting itself.

    When `verbose` or `progress_callback` is set, one monitoring record is
    produced per epoch (`epoca`, `epocas_totales`, `perdida_media`,
    `segundos_epoca`, `segundos_acumulados`, `segundos_restantes_estimados`),
    collected in the returned `"historial_epocas"` list. Timestamps come
    from `time.perf_counter()` taken around the batch loop only -- this
    cannot perturb `torch`/`numpy` RNG state or gradient flow, so training
    numerics are identical whether or not monitoring is enabled.
    """
    optimizer_name = optimizer_name.lower()
    if optimizer_name not in _SUPPORTED_OPTIMIZERS:
        raise ValueError(
            f"Unsupported optimizer_name: {optimizer_name!r}. Use one of {_SUPPORTED_OPTIMIZERS}."
        )

    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)

    resolved_device = torch.device(device)
    model = model.to(resolved_device)
    loss_fn = loss_fn.to(resolved_device)

    X_tensor = torch.as_tensor(np.asarray(X_inst), dtype=torch.float32)
    y_tensor = torch.as_tensor(np.asarray(bag_index.y), dtype=torch.float32)
    n_bags = len(bag_index.offsets) - 1

    if optimizer_name == "adamw":
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    else:
        optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    history: list[dict[str, float]] = []
    historial_epocas: list[dict[str, Any]] = []
    segundos_acumulados = 0.0
    model.train()
    for epoch in range(1, epochs + 1):
        _epoca_t0 = time.perf_counter()
        orden_bolsas = rng.permutation(n_bags)
        sumas = np.zeros(len(_TRACKED_HISTORY_KEYS), dtype=np.float64)
        n_lotes = 0
        for inicio in range(0, n_bags, bag_batch_size):
            lote_bags = orden_bolsas[inicio : inicio + bag_batch_size]
            filas, bolsa_local = _lote_de_instancias(bag_index, lote_bags)

            x_lote = X_tensor[filas].to(resolved_device)
            instance_bag_lote = torch.as_tensor(
                bolsa_local, dtype=torch.long, device=resolved_device
            )
            y_lote = y_tensor[lote_bags].to(resolved_device)

            optimizer.zero_grad()
            model_output = model(x_lote, instance_bag_lote, len(lote_bags))
            # D5/D2: always score reconstruction against the ORIGINAL instance batch.
            componentes = loss_fn.compute_components(model_output, x_lote, y_lote)
            componentes["total_loss"].backward()
            optimizer.step()

            sumas += (
                torch.stack([componentes[key].detach() for key in _TRACKED_HISTORY_KEYS])
                .cpu()
                .numpy()
                .astype(np.float64)
            )
            n_lotes += 1

        promedios = dict(zip(_TRACKED_HISTORY_KEYS, sumas / max(n_lotes, 1)))
        history.append({"epoch": epoch, **promedios})

        segundos_epoca = time.perf_counter() - _epoca_t0
        segundos_acumulados += segundos_epoca
        segundos_restantes_estimados = (
            (epochs - epoch) * (segundos_acumulados / epoch) if epoch < epochs else 0.0
        )
        registro_epoca: dict[str, Any] = {
            "epoca": epoch,
            "epocas_totales": epochs,
            "perdida_media": float(promedios["total_loss"]),
            "segundos_epoca": float(segundos_epoca),
            "segundos_acumulados": float(segundos_acumulados),
            "segundos_restantes_estimados": float(segundos_restantes_estimados),
        }
        historial_epocas.append(registro_epoca)
        if progress_callback is not None:
            progress_callback(registro_epoca)
        if verbose:
            print(
                f"Epoca {epoch}/{epochs} | perdida_media={registro_epoca['perdida_media']:.4f} | "
                f"tiempo_epoca={_formatear_mmss(segundos_epoca)} | "
                f"ETA={_formatear_mmss(segundos_restantes_estimados)}"
            )

    model.eval()
    final = history[-1] if history else {key: float("nan") for key in _TRACKED_HISTORY_KEYS}
    return {
        "model": model,
        "history": history,
        "historial_epocas": historial_epocas,
        **{key: value for key, value in final.items() if key != "epoch"},
    }
