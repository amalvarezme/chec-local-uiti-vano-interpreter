"""Per-sample edge-gate autoencoder built on top of `MGCECDLRegressor`.

Notebook 12's criticality representation is a self-supervised pivot: this
module uses `MGCECDLRegressor` purely as an autoencoder -- `x -> encode -> z
-> gates -> propagate -> encode -> decode -> x-hat` -- trained ONLY against
its own reconstruction of the ORIGINAL input, the fixed expert graph kernel,
and a gate-deviation prior. No supervised target ever enters the loss; see
`sdd/notebook-12-criticality-representation/design` (D1, D2) for the full
rationale, in particular why `agreement_loss`/`kl_loss` are excluded even
though they do not require targets.

Every feature/edge dimension here is derived at runtime from the adjacency
matrix, the feature list, and the edge index passed in by the caller -- this
module must never hardcode a feature or edge count.

Placed under `src/chec_impacto/models/` (not `src/chec_impacto/training/`,
which is under an explicit `Edit` deny in this repository) following the
same precedent as `KernelDensityWeightedMSELoss` and `MGCECDLRegressionLoss`
in `models/mgcecdl.py`: new training-adjacent logic that needs private
helpers from `chec_impacto.training.mgcecdl` imports them lazily (deferred
to `__init__`), never at module top level, to avoid a `models` <->
`training` circular import.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from chec_impacto.models.mgcecdl import MGCECDLRegressor


@dataclass(frozen=True)
class GraphEdgeIndex:
    """A directed edge list into a `(p, p)` adjacency matrix, aligned by NAME.

    `pairs[i]` is `(source_position, target_position)` for `names[i] ==
    (source_name, target_name)`, with positions resolved against the
    `features` order the caller supplied to `construir_edge_index` -- never
    against the iteration order of `preserved_edges` itself.
    """

    pairs: np.ndarray  # (n_edges, 2) int64
    names: tuple[tuple[str, str], ...]
    weights: np.ndarray  # (n_edges,) float32

    @property
    def n_edges(self) -> int:
        return int(self.pairs.shape[0])


def construir_edge_index(
    A: np.ndarray,
    features: Sequence[str],
    preserved_edges: Sequence[Mapping[str, object]],
) -> GraphEdgeIndex:
    """Build a `GraphEdgeIndex` from `preserved_edges`, aligning strictly by NAME.

    `A` is only used to validate shape consistency with `features` -- the
    edge set and its per-edge weight always come from `preserved_edges`
    (as produced by `chec_impacto.data.graph.construir_aristas_preservadas`),
    never from scanning `A` positionally. This is what keeps edge identity
    correct regardless of the order `preserved_edges` happens to be in.
    """
    feature_list = [str(name) for name in features]
    if len(feature_list) != len(set(feature_list)):
        raise ValueError("features contains duplicate names.")

    adjacency = np.asarray(A)
    if adjacency.shape != (len(feature_list), len(feature_list)):
        raise ValueError(
            "A must have shape (len(features), len(features)); got "
            f"{adjacency.shape} for {len(feature_list)} features."
        )

    positions = {name: index for index, name in enumerate(feature_list)}

    pairs: list[tuple[int, int]] = []
    names: list[tuple[str, str]] = []
    weights: list[float] = []
    for edge in preserved_edges:
        source = str(edge["source"])
        target = str(edge["target"])
        if source not in positions or target not in positions:
            raise ValueError(
                f"preserved_edges references a feature not in `features`: {source!r} -> {target!r}"
            )
        pairs.append((positions[source], positions[target]))
        names.append((source, target))
        weights.append(float(edge["weight"]))

    if not pairs:
        raise ValueError("preserved_edges must contain at least one edge.")

    return GraphEdgeIndex(
        pairs=np.asarray(pairs, dtype=np.int64),
        names=tuple(names),
        weights=np.asarray(weights, dtype=np.float32),
    )


def reinyectar_target_como_feature(
    resultado: Mapping[str, object],
    nombre_target: str = "UITI_VANO",
) -> tuple[np.ndarray, list[str]]:
    """Re-inject the regression target into `X` as an extra feature.

    `procesar_dataset_completo` deliberately excludes the target column from
    `features`/`X` (`src/chec_impacto/data/preprocessing.py:135-136`).
    Notebook 12 needs it back as an endogenous predictor. `resultado["y"]` is
    built from the SAME already-filtered frame that produces `resultado["X"]`
    (`preprocessing.py:166,169,204`), so it is row-aligned with `X` BY
    CONSTRUCTION -- this function concatenates `X` with `y` directly and
    deliberately never touches `resultado["df_original_copy"]`, whose index
    is non-contiguous after `preprocessing.py`'s `filtro_uiti_max` filter
    (`:87`) and would be unsafe to join against.
    """
    features = [str(name) for name in resultado["features"]]
    if nombre_target in features:
        raise ValueError(
            f"{nombre_target!r} is already present in resultado['features']; "
            "refusing to re-inject a target that is already a feature."
        )

    X = np.asarray(resultado["X"])
    y = np.asarray(resultado["y"])
    if y.shape[0] != X.shape[0]:
        raise ValueError(
            f"resultado['y'] has {y.shape[0]} rows but resultado['X'] has {X.shape[0]}; "
            "re-injection requires row alignment."
        )
    y = y.reshape(X.shape[0], -1)
    if y.shape[1] != 1:
        raise ValueError("resultado['y'] must be a single-column target for re-injection.")

    X_augmented = np.concatenate([X, y.astype(X.dtype, copy=False)], axis=1)
    features_augmented = [*features, nombre_target]
    return X_augmented, features_augmented


class PerSampleEdgeGateDecoder(nn.Module):
    """`g_v = 2 * sigmoid(Linear(latent_dim, n_edges)(z_v))`.

    Weight AND bias are zero-initialized so `g_v == 1` everywhere at
    construction -- the gated adjacency exactly recovers the base expert
    adjacency at step 0 (`2 * sigmoid(0) == 1`).
    """

    def __init__(self, latent_dim: int, n_edges: int) -> None:
        super().__init__()
        self.linear = nn.Linear(latent_dim, n_edges)
        nn.init.zeros_(self.linear.weight)
        nn.init.zeros_(self.linear.bias)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        return 2.0 * torch.sigmoid(self.linear(z))


class GraphGatedMGCECDLRegressor(nn.Module):
    """Wraps `MGCECDLRegressor` in a two-pass, per-sample gated forward.

    Pass 1 encodes `x` through the base model's modality encoders (gate
    source only, no decode) to obtain a per-sample latent `z`. The gate head
    reads `z` and scatters a per-sample multiplicative gate onto the fixed
    expert adjacency's support (off-support cells stay exactly zero). The
    propagated input `x' = x + alpha * (A_hat^T x)` is then re-encoded and
    decoded through the SAME base model in pass 2 -- this is the "shared
    encoder" the design refers to: both passes go through the identical
    `base` module, not two separate encoders.
    """

    def __init__(
        self,
        base: MGCECDLRegressor,
        adjacency: np.ndarray | torch.Tensor,
        edge_index: GraphEdgeIndex,
        alpha: float,
    ) -> None:
        super().__init__()
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

        # The forward pass scales each gate by `adjacency[row, col]`, but every
        # downstream reader of a per-group reconstructed graph
        # (`grafo_reconstruido_por_grupo`) scales it by `edge_index.weights`.
        # Those are two independent carriers of one quantity. Today they always
        # agree, because `construir_edge_index` and `_edge_index_from_adjacency`
        # both derive from the same matrix -- but nothing enforced it, so a
        # future caller could hand over an edge index whose weights contradict
        # the adjacency and the interpretability layer would describe a graph
        # the model never actually used, silently. Refuse to build instead.
        declared_weights = torch.as_tensor(edge_index.weights, dtype=torch.float32)
        if declared_weights.shape != edge_values.shape or not torch.allclose(
            edge_values, declared_weights, atol=1e-5
        ):
            raise ValueError(
                "edge_index.weights contradicts the adjacency it indexes into: the forward "
                "pass would use adjacency[row, col] while the interpretability layer would "
                "report edge_index.weights. Build the edge index from this same adjacency."
            )

        self.register_buffer("edge_values", edge_values)

        latent_dim = base.n_modalities * base.embed_dim
        self.gate_decoder = PerSampleEdgeGateDecoder(
            latent_dim=latent_dim, n_edges=edge_index.n_edges
        )

    def forward(
        self,
        x: torch.Tensor,
        modality_masks: torch.Tensor | None = None,
    ) -> dict[str, Any]:
        batch_size = x.shape[0]
        n_features = self.adjacency.shape[0]

        # Pass 1: gate source only -- no decode, no reliability/prediction use.
        modality_embeddings, _reliability_scores = self.base._encode_modalities(x)
        z = torch.cat(modality_embeddings, dim=1)
        gates = self.gate_decoder(z)  # (B, n_edges), strictly in (0, 2)

        gated_adjacency = x.new_zeros((batch_size, n_features, n_features))
        gated_adjacency[:, self.edge_rows, self.edge_cols] = gates * self.edge_values.unsqueeze(0)

        propagated = torch.bmm(gated_adjacency.transpose(1, 2), x.unsqueeze(-1)).squeeze(-1)
        propagated_inputs = x + self.alpha * propagated

        # Pass 2: SAME base module, full forward (encode + decode + heads).
        model_output = dict(self.base(propagated_inputs, modality_masks=modality_masks))
        model_output["edge_gates"] = gates
        model_output["gated_adjacency"] = gated_adjacency
        model_output["propagated_inputs"] = propagated_inputs
        return model_output


class GatedSelfSupervisedLoss(nn.Module):
    """Reconstruction (`"soft"`) + Rényi MI + gate-deviation. No targets.

    `agreement_loss`/`kl_loss`/`fused_loss`/`modality_loss` are deliberately
    absent -- see `sdd/notebook-12-criticality-representation/design` (D1):
    `fused_loss`/`modality_loss` need a target that does not exist here, and
    `agreement_loss`/`kl_loss` -- though target-free -- are adverse pressure
    toward exactly the representation collapse the acceptance gate exists to
    detect (their global minimum is reachable by zeroing the very heads that
    would otherwise carry no gradient at all).
    """

    def __init__(
        self,
        feature_mean: np.ndarray | torch.Tensor,
        feature_std: np.ndarray | torch.Tensor,
        adjacency_matrix: np.ndarray | torch.Tensor,
        rbf_sigma: float = 1.0,
        lambda_reconstruction: float = 0.01,
        lambda_mutual_information: float = 0.01,
        lambda_gate_deviation: float = 0.0,
        reconstruction_normalization: str = "clip",
    ) -> None:
        super().__init__()
        if reconstruction_normalization != "soft":
            raise ValueError(
                "reconstruction_normalization must be explicitly 'soft' for the gated "
                f"autoencoder (received: {reconstruction_normalization!r}). 'clip' pins the "
                "reconstruction term at exactly 1.0 with zero gradient once the raw MSE "
                "exceeds 1 -- see models/mgcecdl.py:598-620 for the measured evidence."
            )

        # Deferred import -- mirrors `MGCECDLRegressionLoss` in `models/mgcecdl.py`
        # (see that class's docstring): avoids a `models` <-> `training` circular
        # import while still genuinely reusing, not reimplementing, the shared
        # graph-reconstruction + mutual-information computation.
        from chec_impacto.training.mgcecdl import _MGCECDLGraphReconstructionLoss

        self._graph_reconstruction = _MGCECDLGraphReconstructionLoss(
            feature_mean=feature_mean,
            feature_std=feature_std,
            adjacency_matrix=adjacency_matrix,
            rbf_sigma=rbf_sigma,
            lambda_reconstruction=lambda_reconstruction,
            lambda_mutual_information=lambda_mutual_information,
        )
        self.reconstruction_normalization = reconstruction_normalization
        self.lambda_gate_deviation = float(lambda_gate_deviation)

    def compute_components(
        self,
        model_output: Mapping[str, torch.Tensor | list[torch.Tensor] | tuple[str, ...]],
        inputs: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        # `inputs` MUST be the ORIGINAL x, never `model_output["propagated_inputs"]` --
        # see design D2. `_compute_graph_reconstruction_components` takes `inputs`
        # explicitly precisely so this stays the caller's responsibility, not something
        # this module can silently get wrong internally.
        graph_components = self._graph_reconstruction._compute_graph_reconstruction_components(
            model_output, inputs
        )

        # `_MGCECDLGraphReconstructionLoss` normalizes as `clip(MSE, 0, 1)`, a dead fixed
        # point once MSE exceeds 1 (see `__init__`'s ValueError message). The soft
        # replacement -- `MSE / (1 + MSE)` -- keeps range [0, 1) and monotonicity but has a
        # strictly positive derivative everywhere, so the term keeps teaching.
        raw_reconstruction = graph_components["reconstruction_loss_raw"]
        soft_reconstruction = raw_reconstruction / (1.0 + raw_reconstruction)

        gates = model_output["edge_gates"]
        gate_deviation_loss = self.lambda_gate_deviation * (gates - 1.0).abs().mean()

        total_loss = (
            self._graph_reconstruction.lambda_reconstruction * soft_reconstruction
            + self._graph_reconstruction.lambda_mutual_information
            * graph_components["mutual_information_loss"]
            + gate_deviation_loss
        )

        return {
            "total_loss": total_loss,
            "reconstruction_loss": soft_reconstruction,
            "reconstruction_loss_raw": raw_reconstruction,
            "mutual_information": graph_components["mutual_information"],
            "mutual_information_normalized": graph_components["mutual_information_normalized"],
            "mutual_information_loss": graph_components["mutual_information_loss"],
            "gate_deviation_loss": gate_deviation_loss,
        }

    def forward(
        self,
        model_output: Mapping[str, torch.Tensor | list[torch.Tensor] | tuple[str, ...]],
        inputs: torch.Tensor,
    ) -> torch.Tensor:
        return self.compute_components(model_output, inputs)["total_loss"]


_TRACKED_HISTORY_KEYS = (
    "total_loss",
    "reconstruction_loss",
    "reconstruction_loss_raw",
    "mutual_information_loss",
    # The ACHIEVED normalized mutual information, not just its loss share.
    # `resumen_barrido_lambda_mi` reads this key unconditionally, because a
    # higher lambda mechanically raises the term's share of the loss without
    # necessarily raising what the model actually captures.
    "mutual_information_normalized",
    "gate_deviation_loss",
)

_SUPPORTED_OPTIMIZERS = ("adam", "adamw")


def entrenar_gated_autoencoder(
    model: GraphGatedMGCECDLRegressor,
    loss_fn: GatedSelfSupervisedLoss,
    X_past: np.ndarray | torch.Tensor,
    *,
    epochs: int,
    batch_size: int = 1024,
    lr: float = 1e-3,
    weight_decay: float = 1e-5,
    optimizer_name: str = "adamw",
    seed: int = 42,
    device: str | torch.device = "cpu",
) -> dict[str, Any]:
    """Train `model` self-supervised (reconstruction-only, D2) on `X_past`.

    `X_past` must already be the chronologically-past partition -- this
    function performs no splitting itself (see
    `chec_impacto.interpretability.mgcecdl_graph.split_cronologico_p70`,
    a PR2 concern).
    """
    optimizer_name = optimizer_name.lower()
    if optimizer_name not in _SUPPORTED_OPTIMIZERS:
        raise ValueError(
            f"Unsupported optimizer_name: {optimizer_name!r}. Use one of {_SUPPORTED_OPTIMIZERS}."
        )

    torch.manual_seed(seed)
    np.random.seed(seed)

    resolved_device = torch.device(device)
    model = model.to(resolved_device)
    loss_fn = loss_fn.to(resolved_device)

    X_tensor = torch.as_tensor(np.asarray(X_past), dtype=torch.float32)
    dataset = TensorDataset(X_tensor)
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, generator=generator)

    if optimizer_name == "adamw":
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    else:
        optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    history: list[dict[str, float]] = []
    model.train()
    for epoch in range(1, epochs + 1):
        component_sums = np.zeros(len(_TRACKED_HISTORY_KEYS), dtype=np.float64)
        n_batches = 0
        for (xb,) in loader:
            xb = xb.to(resolved_device)
            optimizer.zero_grad()
            model_output = model(xb)
            # D2: always score against the ORIGINAL batch `xb`, never
            # `model_output["propagated_inputs"]`.
            components = loss_fn.compute_components(model_output, xb)
            components["total_loss"].backward()
            optimizer.step()
            component_sums += (
                torch.stack([components[key].detach() for key in _TRACKED_HISTORY_KEYS])
                .cpu()
                .numpy()
                .astype(np.float64)
            )
            n_batches += 1
        epoch_components = dict(
            zip(_TRACKED_HISTORY_KEYS, component_sums / max(n_batches, 1))
        )
        history.append({"epoch": epoch, **epoch_components})

    model.eval()
    final = history[-1] if history else {key: float("nan") for key in _TRACKED_HISTORY_KEYS}
    return {
        "model": model,
        "history": history,
        **{key: value for key, value in final.items() if key != "epoch"},
    }


# ---------------------------------------------------------------------------
# Checkpoint persistence
#
# A gated model is NOT reconstructible from its `state_dict` alone: the base
# `MGCECDLRegressor`'s shape comes from `modality_feature_indices`, and the
# gated wrapper additionally needs the fixed adjacency, the edge index (with
# its NAMES -- positions alone would silently re-bind every edge to a
# different feature pair) and `alpha`. All of it travels in one file.
# ---------------------------------------------------------------------------


_CONFIGURACION_REQUERIDA = (
    "modality_feature_indices",
    "hidden_dim",
    "embed_dim",
    "dropout",
)


def _validar_configuracion(configuracion: Mapping[str, object]) -> None:
    faltantes = [key for key in _CONFIGURACION_REQUERIDA if key not in configuracion]
    if faltantes:
        raise ValueError(
            "configuracion is missing the key(s) required to rebuild the base model: "
            f"{', '.join(faltantes)}. Required keys: {', '.join(_CONFIGURACION_REQUERIDA)}."
        )


def guardar_modelo_gated(
    path: str | Path,
    model: GraphGatedMGCECDLRegressor,
    *,
    features: Sequence[str],
    configuracion: Mapping[str, object],
    metadata: Mapping[str, object] | None = None,
) -> Path:
    """Write a self-contained `torch.save` checkpoint of a gated model.

    `configuracion` must carry everything `cargar_modelo_gated` needs to
    rebuild the base `MGCECDLRegressor` -- validation happens BEFORE anything
    touches the filesystem, so a rejected configuration never leaves a
    half-written checkpoint behind. Parent directories are created as needed;
    the resolved destination is returned.
    """
    _validar_configuracion(configuracion)

    destino = Path(path).resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)

    edge_index = model.edge_index
    checkpoint: dict[str, Any] = {
        "state_dict": model.state_dict(),
        "features": [str(name) for name in features],
        "configuracion": dict(configuracion),
        "adjacency": model.adjacency.detach().cpu().numpy(),
        "edge_index_pairs": np.asarray(edge_index.pairs, dtype=np.int64),
        "edge_index_names": tuple(
            (str(source), str(target)) for source, target in edge_index.names
        ),
        "edge_index_weights": np.asarray(edge_index.weights, dtype=np.float32),
        "alpha": float(model.alpha),
        "metadata": dict(metadata) if metadata is not None else {},
    }
    torch.save(checkpoint, destino)
    return destino


def cargar_modelo_gated(
    path: str | Path,
    *,
    device: str | torch.device = "cpu",
) -> dict:
    """Rebuild a `GraphGatedMGCECDLRegressor` from a `guardar_modelo_gated`
    checkpoint, in `eval()` mode on `device`.

    `load_state_dict` runs STRICTLY: a checkpoint whose architecture does not
    match the stored `configuracion` fails loudly here rather than silently
    loading a partially-initialized model whose gates would be meaningless.

    Returns `{"model", "features", "edge_index", "adjacency", "configuracion",
    "metadata"}`.
    """
    origen = Path(path).resolve()
    resolved_device = torch.device(device)

    # `weights_only=False`: this checkpoint deliberately carries the numpy
    # adjacency/edge arrays and the configuration mapping needed to rebuild
    # the architecture, not just tensors.
    checkpoint = torch.load(origen, map_location=resolved_device, weights_only=False)

    configuracion = dict(checkpoint["configuracion"])
    _validar_configuracion(configuracion)

    base = MGCECDLRegressor(
        modality_feature_indices=configuracion["modality_feature_indices"],
        hidden_dim=int(configuracion["hidden_dim"]),
        embed_dim=int(configuracion["embed_dim"]),
        dropout=float(configuracion["dropout"]),
        temperature=float(configuracion.get("temperature", 1.0)),
    )

    edge_index = GraphEdgeIndex(
        pairs=np.asarray(checkpoint["edge_index_pairs"], dtype=np.int64),
        names=tuple(
            (str(source), str(target)) for source, target in checkpoint["edge_index_names"]
        ),
        weights=np.asarray(checkpoint["edge_index_weights"], dtype=np.float32),
    )
    adjacency = np.asarray(checkpoint["adjacency"])

    model = GraphGatedMGCECDLRegressor(
        base=base,
        adjacency=adjacency,
        edge_index=edge_index,
        alpha=float(checkpoint["alpha"]),
    )
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    model.eval()
    model = model.to(resolved_device)

    return {
        "model": model,
        "features": [str(name) for name in checkpoint["features"]],
        "edge_index": edge_index,
        "adjacency": adjacency,
        "configuracion": configuracion,
        "metadata": dict(checkpoint["metadata"]),
    }
