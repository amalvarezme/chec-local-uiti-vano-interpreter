from __future__ import annotations

from contextlib import contextmanager
import json
import zipfile

import numpy as np
import scipy
import torch
from pytorch_tabnet.tab_model import TabNetClassifier, TabNetRegressor
from pytorch_tabnet.utils import PredictDataset, SparsePredictDataset
from torch.utils.data import DataLoader


DEFAULT_TABNET_BATCH_SIZE = 1024


def resolver_config_entrenamiento_tabnet(params=None):
    """Derive fit-only settings that pytorch-tabnet does not serialize."""
    params = params or {}
    batch_size = int(params.get("batch_size", DEFAULT_TABNET_BATCH_SIZE))
    virtual_batch_size = int(params.get("virtual_batch_size", batch_size // 4))
    if batch_size < 2:
        raise ValueError("batch_size debe ser mayor o igual a 2.")
    if not 1 < virtual_batch_size <= batch_size:
        raise ValueError(
            "virtual_batch_size debe ser mayor que 1 y menor o igual a batch_size."
        )
    return {
        "batch_size": batch_size,
        "virtual_batch_size": virtual_batch_size,
    }


def configurar_entrenamiento_tabnet(model, training_config):
    """Restore fit-only settings omitted by pytorch-tabnet save_model."""
    training_config = resolver_config_entrenamiento_tabnet(training_config)
    model.batch_size = training_config["batch_size"]
    virtual_batch_size = training_config["virtual_batch_size"]
    model.virtual_batch_size = virtual_batch_size
    if hasattr(model, "network"):
        for module in model.network.modules():
            if hasattr(module, "virtual_batch_size"):
                module.virtual_batch_size = virtual_batch_size
    return model


@contextmanager
def _batch_norm_inference(network):
    """Use batch statistics without permanently changing BatchNorm buffers."""
    batch_norms = [
        module for module in network.modules() if isinstance(module, torch.nn.BatchNorm1d)
    ]
    snapshots = [
        (
            module.training,
            module.running_mean.detach().clone() if module.running_mean is not None else None,
            module.running_var.detach().clone() if module.running_var is not None else None,
            module.num_batches_tracked.detach().clone()
            if module.num_batches_tracked is not None
            else None,
        )
        for module in batch_norms
    ]

    network.eval()
    for module in batch_norms:
        module.train()

    try:
        yield
    finally:
        for module, (was_training, running_mean, running_var, num_batches) in zip(
            batch_norms, snapshots
        ):
            module.train(was_training)
            if running_mean is not None:
                module.running_mean.copy_(running_mean)
            if running_var is not None:
                module.running_var.copy_(running_var)
            if num_batches is not None:
                module.num_batches_tracked.copy_(num_batches)
        network.eval()


class _PortableBatchNormPredictionMixin:
    def save_model(self, path):
        filepath = super().save_model(path)
        training_config = resolver_config_entrenamiento_tabnet(
            {
                "batch_size": self.batch_size,
                "virtual_batch_size": self.virtual_batch_size,
            }
        )
        with zipfile.ZipFile(filepath, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "training_config.json",
                json.dumps(training_config, indent=2),
            )
        return filepath

    def _predict_raw(self, X):
        dataset = SparsePredictDataset(X) if scipy.sparse.issparse(X) else PredictDataset(X)
        dataloader = DataLoader(dataset, batch_size=self.batch_size, shuffle=False)
        results = []

        with _batch_norm_inference(self.network), torch.no_grad():
            for data in dataloader:
                data = data.to(self.device).float()
                output, _ = self.network(data)
                results.append(output.cpu().numpy())

        return np.vstack(results)


class CustomTabNetClassifier(_PortableBatchNormPredictionMixin, TabNetClassifier):
    """TabNetClassifier con inferencia portable entre CPU y GPU."""

    def predict(self, X):
        return self.predict_func(self._predict_raw(X))

    def predict_proba(self, X):
        return torch.softmax(
            torch.from_numpy(self._predict_raw(X)), dim=1
        ).numpy()


class CustomTabNetRegressor(_PortableBatchNormPredictionMixin, TabNetRegressor):
    """TabNetRegressor con salida no negativa e inferencia portable."""

    def compute_loss(self, y_pred, y_true):
        return self.loss_fn(torch.relu(y_pred), y_true)

    def _predict_batch(self, X):
        return torch.relu(torch.from_numpy(super()._predict_batch(X))).numpy()

    def predict(self, X):
        return np.maximum(self._predict_raw(X), 0.0)


def resolve_tabnet_device():
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def build_optimizer(optimizer_type, learning_rate, momentum, weight_decay):
    if optimizer_type == "adam":
        return torch.optim.Adam, {
            "lr": float(min(max(learning_rate, 1e-4), 3e-3)),
            "weight_decay": weight_decay,
        }

    if optimizer_type == "adamw":
        return torch.optim.AdamW, {
            "lr": float(min(max(learning_rate, 1e-4), 3e-3)),
            "weight_decay": weight_decay,
        }

    if optimizer_type == "sgd":
        return torch.optim.SGD, {
            "lr": float(min(max(learning_rate, 1e-3), 1e-1)),
            "momentum": momentum,
            "weight_decay": weight_decay,
        }

    if optimizer_type == "rmsprop":
        return torch.optim.RMSprop, {
            "lr": float(min(max(learning_rate, 1e-4), 3e-3)),
            "momentum": momentum,
            "weight_decay": weight_decay,
        }

    raise ValueError(f"Optimizador no soportado: {optimizer_type}")


def sugerir_hiperparametros_tabnet(trial, modo=None):
    params = {
        "n_d": trial.suggest_int("n_d", 1, 32),
        "n_a": trial.suggest_int("n_a", 1, 64),
        "n_steps": trial.suggest_int("n_steps", 1, 5),
        "gamma": trial.suggest_float("gamma", 1.0, 2.0),
        "lambda_sparse": trial.suggest_float("lambda_sparse", 1e-6, 1e-3, log=True),
        "mask_type": trial.suggest_categorical("mask_type", ["entmax", "sparsemax"]),
        "emb": trial.suggest_int("emb", 2, 36),
        "momentum": trial.suggest_float("momentum", 0.5, 0.95),
        "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-1, log=True),
        "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-4, log=True),
        "scheduler_gamma": trial.suggest_float("scheduler_gamma", 0.1, 0.9),
        "step_size": trial.suggest_int("step_size", 2, 10),
        "optimizer_type": trial.suggest_categorical(
            "optimizer_type", ["adam", "adamw", "sgd", "rmsprop"]
        ),
        "batch_size": DEFAULT_TABNET_BATCH_SIZE,
    }
    if modo == "regresion":
        params["kmse_sigma"] = trial.suggest_categorical(
            "kmse_sigma", [0.01, 0.05, 0.1, 0.2, 0.4]
        )
    return params


def make_tabnet(features, categorical_columns, categorical_dims, params):
    cat_idxs = [i for i, feature in enumerate(features) if feature in categorical_columns]
    cat_dims = [
        categorical_dims[feature]
        for feature in features
        if feature in categorical_columns
    ]
    cat_emb_dim = [min(params["emb"], max(4, (dim + 1) // 2)) for dim in cat_dims]
    return cat_idxs, cat_dims, cat_emb_dim


def crear_modelo_tabnet(
    params,
    modo,
    features,
    categorical_columns,
    categorical_dims,
    device_name=None,
    verbose=True,
):
    training_config = resolver_config_entrenamiento_tabnet(params)
    cat_idxs, cat_dims, cat_emb_dim = make_tabnet(
        features,
        categorical_columns,
        categorical_dims,
        params,
    )

    optimizer_fn, optimizer_params = build_optimizer(
        params["optimizer_type"],
        params["learning_rate"],
        params["momentum"],
        params["weight_decay"],
    )

    common_params = dict(
        cat_dims=cat_dims,
        cat_emb_dim=cat_emb_dim,
        cat_idxs=cat_idxs,
        n_d=params["n_d"],
        n_a=params["n_a"],
        n_steps=params["n_steps"],
        gamma=params["gamma"],
        lambda_sparse=params["lambda_sparse"],
        mask_type=params["mask_type"],
        optimizer_fn=optimizer_fn,
        optimizer_params=optimizer_params,
        scheduler_params={
            "gamma": params["scheduler_gamma"],
            "step_size": params["step_size"],
        },
        scheduler_fn=torch.optim.lr_scheduler.StepLR,
        device_name=device_name or resolve_tabnet_device(),
        verbose=verbose,
    )

    if modo == "clasificacion":
        model = CustomTabNetClassifier(**common_params)
        return configurar_entrenamiento_tabnet(model, training_config)

    if modo == "regresion":
        model = CustomTabNetRegressor(**common_params)
        return configurar_entrenamiento_tabnet(model, training_config)

    raise ValueError("modo debe ser 'regresion' o 'clasificacion'.")


def cargar_modelo_tabnet(
    modo,
    model_zip_path,
    params=None,
):
    model = (
        CustomTabNetClassifier()
        if modo == "clasificacion"
        else CustomTabNetRegressor()
    )
    model.load_model(model_zip_path)
    training_config = None
    with zipfile.ZipFile(model_zip_path) as archive:
        if "training_config.json" in archive.namelist():
            training_config = json.loads(archive.read("training_config.json"))
    if training_config is None:
        training_config = resolver_config_entrenamiento_tabnet(params)
    return configurar_entrenamiento_tabnet(model, training_config)
