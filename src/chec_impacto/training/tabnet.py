from __future__ import annotations

import os
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import optuna
import pandas as pd
import torch
from optuna.pruners import SuccessiveHalvingPruner
from optuna.samplers import GPSampler
from optuna.storages import JournalFileStorage, JournalStorage
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    auc,
    balanced_accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

from chec_impacto.data import preparar_splits_estratificados
from chec_impacto.models.tabnet import (
    cargar_modelo_tabnet,
    crear_modelo_tabnet,
    resolver_config_entrenamiento_tabnet,
    sugerir_hiperparametros_tabnet,
)


MODEL_CONFIG = {
    "clasificacion": {
        "model_name": "best_tabnet_classifier_model",
        "params_name": "tabnet_best_params_classification.pkl",
        "study_name": "tabnet_classification",
        "journal_name": "tabnet_classification_params.journal",
        "direction": "maximize",
        "label": "classification",
    },
    "regresion": {
        "model_name": "best_tabnet_regressor_model",
        "params_name": "tabnet_best_params_regression.pkl",
        "study_name": "tabnet_regression",
        "journal_name": "tabnet_regression_params.journal",
        "direction": "minimize",
        "label": "regression",
    },
}


def make_kmse_loss(sigma):
    sigma = float(sigma)

    def kmse_loss(y_pred, y_true):
        squared_error = (y_true - y_pred) ** 2
        if squared_error.ndim > 1:
            squared_error = squared_error.flatten(start_dim=1).sum(dim=1)
        similarity = torch.exp(squared_error.neg() / (2 * sigma**2)).mean()
        return 1 - similarity

    return kmse_loss


def get_model_paths(modo, model_dir):
    cfg = MODEL_CONFIG[modo]
    model_dir = Path(model_dir)
    model_path = model_dir / cfg["model_name"]
    return {
        "model_path": str(model_path),
        "model_zip_path": str(model_path) + ".zip",
        "params_path": str(model_dir / cfg["params_name"]),
        "journal_path": str(model_dir / cfg["journal_name"]),
    }


def objective_classification(
    trial,
    X_train,
    y_train,
    X_valid,
    y_valid,
    features,
    categorical_columns,
    categorical_dims,
):
    params = sugerir_hiperparametros_tabnet(trial, modo="clasificacion")
    training_config = resolver_config_entrenamiento_tabnet(params)
    batch_size = training_config["batch_size"]
    virtual_batch_size = training_config["virtual_batch_size"]

    y_train_cls = y_train.reshape(-1).astype(int)
    y_valid_cls = y_valid.reshape(-1).astype(int)

    model = crear_modelo_tabnet(
        params,
        modo="clasificacion",
        features=features,
        categorical_columns=categorical_columns,
        categorical_dims=categorical_dims,
        verbose=False,
    )
    model.fit(
        X_train=X_train,
        y_train=y_train_cls,
        eval_set=[(X_train, y_train_cls), (X_valid, y_valid_cls)],
        eval_name=["train", "valid"],
        eval_metric=["accuracy", "logloss", "balanced_accuracy"],
        max_epochs=60,
        patience=40,
        batch_size=batch_size,
        virtual_batch_size=virtual_batch_size,
        num_workers=1,
        drop_last=False,
    )
    return float(model.best_cost)


def objective_regression(
    trial,
    X_train,
    y_train,
    X_valid,
    y_valid,
    features,
    categorical_columns,
    categorical_dims,
):
    params = sugerir_hiperparametros_tabnet(trial, modo="regresion")
    training_config = resolver_config_entrenamiento_tabnet(params)
    batch_size = training_config["batch_size"]
    virtual_batch_size = training_config["virtual_batch_size"]

    model = crear_modelo_tabnet(
        params,
        modo="regresion",
        features=features,
        categorical_columns=categorical_columns,
        categorical_dims=categorical_dims,
        verbose=False,
    )
    model.fit(
        X_train=X_train,
        y_train=y_train,
        eval_set=[(X_train, y_train), (X_valid, y_valid)],
        eval_name=["train", "valid"],
        eval_metric=["mae"],
        loss_fn=make_kmse_loss(params["kmse_sigma"]),
        max_epochs=60,
        patience=40,
        batch_size=batch_size,
        virtual_batch_size=virtual_batch_size,
        num_workers=1,
        drop_last=False,
    )
    return float(model.best_cost)


def crear_objective_tabnet(
    modo,
    X_train,
    y_train,
    X_valid,
    y_valid,
    features,
    categorical_columns,
    categorical_dims,
):
    if modo == "clasificacion":
        objective_fn = objective_classification
    elif modo == "regresion":
        objective_fn = objective_regression
    else:
        raise ValueError("modo debe ser 'regresion' o 'clasificacion'.")

    def objective(trial):
        return objective_fn(
            trial,
            X_train,
            y_train,
            X_valid,
            y_valid,
            features,
            categorical_columns,
            categorical_dims,
        )

    return objective


def buscar_parametros_tabnet(
    modo_objetivo,
    model_dir,
    X_train,
    y_train,
    X_valid,
    y_valid,
    features,
    categorical_columns,
    categorical_dims,
    n_trials=7,
):
    modo_objetivo = modo_objetivo.lower()
    if modo_objetivo not in MODEL_CONFIG:
        raise ValueError("modo_objetivo debe ser 'regresion' o 'clasificacion'.")

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    paths = get_model_paths(modo_objetivo, model_dir)
    cfg = MODEL_CONFIG[modo_objetivo]

    if os.path.exists(paths["model_zip_path"]):
        print(
            f"Modelo {modo_objetivo} encontrado. "
            f"No se ejecuta busqueda: {paths['model_zip_path']}"
        )
        params = joblib.load(paths["params_path"]) if os.path.exists(paths["params_path"]) else None
        return params, paths, cfg

    pruner = SuccessiveHalvingPruner(
        min_resource=10,
        reduction_factor=3,
        min_early_stopping_rate=0,
    )
    storage_tabnet = JournalStorage(JournalFileStorage(paths["journal_path"]))

    study = optuna.create_study(
        study_name=cfg["study_name"],
        storage=storage_tabnet,
        direction=cfg["direction"],
        load_if_exists=True,
        pruner=pruner,
        sampler=GPSampler(),
    )
    study.optimize(
        crear_objective_tabnet(
            modo_objetivo,
            X_train,
            y_train,
            X_valid,
            y_valid,
            features,
            categorical_columns,
            categorical_dims,
        ),
        n_trials=n_trials,
    )

    print(f"Best hyperparameters for {cfg['label']}: ", study.best_params)
    print(f"Best value for {cfg['label']}: ", study.best_value)

    params = study.best_params
    joblib.dump(params, paths["params_path"])
    print(f"Mejores parametros guardados en: {paths['params_path']}")
    return params, paths, cfg


def buscar_estudio_optuna_tabnet(
    modo_objetivo,
    model_dir,
    X_train,
    y_train,
    X_valid,
    y_valid,
    features,
    categorical_columns,
    categorical_dims,
    n_trials=7,
):
    """Ejecuta la busqueda y devuelve unicamente el objeto Study de Optuna."""
    modo_objetivo = modo_objetivo.lower()
    if modo_objetivo not in MODEL_CONFIG:
        raise ValueError("modo_objetivo debe ser 'regresion' o 'clasificacion'.")

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    paths = get_model_paths(modo_objetivo, model_dir)
    cfg = MODEL_CONFIG[modo_objetivo]

    pruner = SuccessiveHalvingPruner(
        min_resource=10,
        reduction_factor=3,
        min_early_stopping_rate=0,
    )
    storage_tabnet = JournalStorage(JournalFileStorage(paths["journal_path"]))

    study = optuna.create_study(
        study_name=cfg["study_name"],
        storage=storage_tabnet,
        direction=cfg["direction"],
        load_if_exists=True,
        pruner=pruner,
        sampler=GPSampler(),
    )
    study.optimize(
        crear_objective_tabnet(
            modo_objetivo,
            X_train,
            y_train,
            X_valid,
            y_valid,
            features,
            categorical_columns,
            categorical_dims,
        ),
        n_trials=n_trials,
    )

    print(f"Best hyperparameters for {cfg['label']}: ", study.best_params)
    print(f"Best value for {cfg['label']}: ", study.best_value)
    return study


def guardar_estudio_optuna(study, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(study, output_path)
    print(f"Objeto Optuna guardado en: {output_path}")
    return output_path


def cargar_estudio_optuna(input_path):
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"No existe el objeto Optuna: {input_path}")
    return joblib.load(input_path)


def cargar_o_entrenar_tabnet(
    modo_objetivo,
    params,
    paths,
    X_train,
    y_train,
    X_valid,
    y_valid,
    features,
    categorical_columns,
    categorical_dims,
    max_epochs=2,
    patience=70,
):
    if os.path.exists(paths["model_zip_path"]):
        print(f"Modelo {modo_objetivo} encontrado. Cargando desde: {paths['model_zip_path']}")
        model = cargar_modelo_tabnet(modo_objetivo, paths["model_zip_path"])
        print("Modelo cargado correctamente.")
        return model

    print(f"Modelo {modo_objetivo} no encontrado. Entrenando el mejor modelo...")

    if params is None and os.path.exists(paths["params_path"]):
        params = joblib.load(paths["params_path"])

    if params is None:
        raise ValueError("No hay mejores parametros disponibles. Ejecuta primero la busqueda Optuna.")

    best_params = params.copy()
    training_config = resolver_config_entrenamiento_tabnet(best_params)
    best_params.update(training_config)
    batch_size = training_config["batch_size"]
    virtual_batch_size = training_config["virtual_batch_size"]

    model = crear_modelo_tabnet(
        best_params,
        modo=modo_objetivo,
        features=features,
        categorical_columns=categorical_columns,
        categorical_dims=categorical_dims,
        verbose=True,
    )

    if modo_objetivo == "clasificacion":
        y_train_fit = y_train.reshape(-1).astype(int)
        y_valid_fit = y_valid.reshape(-1).astype(int)
        eval_metric = ["accuracy", "logloss", "balanced_accuracy"]
        fit_kwargs = {}
    else:
        y_train_fit = y_train
        y_valid_fit = y_valid
        eval_metric = ["mae"]
        fit_kwargs = {"loss_fn": make_kmse_loss(best_params.get("kmse_sigma", 0.1))}

    model.fit(
        X_train=X_train,
        y_train=y_train_fit,
        eval_set=[(X_train, y_train_fit), (X_valid, y_valid_fit)],
        eval_name=["train", "valid"],
        eval_metric=eval_metric,
        max_epochs=max_epochs,
        patience=patience,
        batch_size=batch_size,
        virtual_batch_size=virtual_batch_size,
        num_workers=1,
        drop_last=False,
        **fit_kwargs,
    )

    model.save_model(paths["model_path"])
    print(f"Modelo guardado en: {paths['model_zip_path']}")

    reloaded_model = cargar_modelo_tabnet(
        modo_objetivo,
        paths["model_zip_path"],
        params=best_params,
    )
    if modo_objetivo == "clasificacion":
        original_predictions = np.asarray(model.predict_proba(X_valid))
        reloaded_predictions = np.asarray(reloaded_model.predict_proba(X_valid))
    else:
        original_predictions = np.asarray(model.predict(X_valid))
        reloaded_predictions = np.asarray(reloaded_model.predict(X_valid))
    if not np.allclose(original_predictions, reloaded_predictions, rtol=1e-5, atol=1e-6):
        max_difference = float(np.max(np.abs(original_predictions - reloaded_predictions)))
        raise RuntimeError(
            "El modelo recargado no reproduce las predicciones de validacion. "
            f"Diferencia maxima: {max_difference}"
        )

    print("Verificacion guardar/recargar completada correctamente.")
    return reloaded_model


def cargar_modelos_disponibles(model_dir, modelos_entrenados=None):
    modelos_entrenados = modelos_entrenados or {}
    modelos_disponibles = {}
    for modo in ["clasificacion", "regresion"]:
        paths_modo = get_model_paths(modo, model_dir)
        if modo in modelos_entrenados:
            modelos_disponibles[modo] = modelos_entrenados[modo]
        elif os.path.exists(paths_modo["model_zip_path"]):
            modelos_disponibles[modo] = cargar_modelo_tabnet(modo, paths_modo["model_zip_path"])

    if not modelos_disponibles:
        raise ValueError("No hay modelos guardados o entrenados para evaluar.")

    return modelos_disponibles


def obtener_splits_para_modo(modo, modo_objetivo, splits, X, y):
    if modo == modo_objetivo:
        return splits
    return preparar_splits_estratificados(X, y, modo=modo)


def evaluar_clasificacion(model, splits_modo):
    X_test_m = splits_modo["X_test"]
    y_true = np.asarray(splits_modo["y_test"]).reshape(-1).astype(int)
    y_pred = np.asarray(model.predict(X_test_m)).reshape(-1).astype(int)
    y_prob = model.predict_proba(X_test_m)

    classes = np.unique(np.concatenate([y_true, y_pred]))
    n_classes = len(classes)

    print("\n===== Rendimiento clasificación =====")
    print("Clases encontradas:", classes)
    print("Número de clases:", n_classes)

    cm = confusion_matrix(y_true, y_pred, labels=classes)
    cm_norm = confusion_matrix(y_true, y_pred, labels=classes, normalize="true")

    accuracy = accuracy_score(y_true, y_pred)
    balanced_acc = balanced_accuracy_score(y_true, y_pred)
    precision_macro = precision_score(y_true, y_pred, average="macro", zero_division=0)
    recall_macro = recall_score(y_true, y_pred, average="macro", zero_division=0)
    f1_macro = f1_score(y_true, y_pred, average="macro", zero_division=0)
    kappa = cohen_kappa_score(y_true, y_pred)
    mcc = matthews_corrcoef(y_true, y_pred)

    stats_por_clase = []
    total = cm.sum()

    for i, cls in enumerate(classes):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        tn = total - tp - fp - fn

        sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        precision_cls = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        npv = tn / (tn + fn) if (tn + fn) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
        f1_cls = (
            2 * precision_cls * sensitivity / (precision_cls + sensitivity)
            if (precision_cls + sensitivity) > 0
            else 0.0
        )

        stats_por_clase.append({
            "clase": cls,
            "TN": tn,
            "FP": fp,
            "FN": fn,
            "TP": tp,
            "precision": precision_cls,
            "recall_sensibilidad": sensitivity,
            "specificity_especificidad": specificity,
            "npv": npv,
            "f1": f1_cls,
            "fpr": fpr,
            "fnr": fnr,
        })

    df_stats_por_clase = pd.DataFrame(stats_por_clase)

    estadisticos_globales = pd.DataFrame({
        "Métrica": [
            "Accuracy",
            "Balanced Accuracy",
            "Precision Macro",
            "Recall Macro",
            "F1 Macro",
            "Kappa",
            "MCC",
        ],
        "Valor": [
            accuracy,
            balanced_acc,
            precision_macro,
            recall_macro,
            f1_macro,
            kappa,
            mcc,
        ],
    })

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    disp = ConfusionMatrixDisplay(confusion_matrix=cm_norm, display_labels=classes)
    disp.plot(ax=axes[0], values_format=".2f", colorbar=False)
    axes[0].set_title("Matriz de confusión normalizada")

    if n_classes == 2:
        y_score = y_prob[:, 1]
        fpr, tpr, _ = roc_curve(y_true, y_score)
        roc_auc = auc(fpr, tpr)
        axes[1].plot(fpr, tpr, label=f"ROC clase positiva, AUC = {roc_auc:.4f}")
        estadisticos_globales.loc[len(estadisticos_globales)] = ["AUC", roc_auc]
    else:
        for i, cls in enumerate(classes):
            y_true_bin = (y_true == cls).astype(int)
            y_score_cls = y_prob[:, i]
            fpr, tpr, _ = roc_curve(y_true_bin, y_score_cls)
            roc_auc = auc(fpr, tpr)
            axes[1].plot(fpr, tpr, label=f"Clase {cls}, AUC = {roc_auc:.4f}")

        auc_macro = roc_auc_score(y_true, y_prob, multi_class="ovr", average="macro")
        estadisticos_globales.loc[len(estadisticos_globales)] = ["AUC Macro OvR", auc_macro]

    axes[1].plot([0, 1], [0, 1], linestyle="--")
    axes[1].set_title("Curva ROC" if n_classes == 2 else "Curva ROC multiclase OvR")
    axes[1].set_xlabel("False Positive Rate")
    axes[1].set_ylabel("True Positive Rate")
    axes[1].legend(loc="lower right")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()

    print("\nEstadísticos globales:")
    print(estadisticos_globales)
    print("\nEstadísticos por clase:")
    print(df_stats_por_clase)

    return estadisticos_globales, df_stats_por_clase


def evaluar_regresion(model, splits_modo):
    X_test_m = splits_modo["X_test"]
    y_real = np.asarray(splits_modo["y_test"]).reshape(-1)
    y_pred = np.asarray(model.predict(X_test_m)).reshape(-1)

    df_eval = pd.DataFrame({
        "y_real": y_real,
        "y_pred": y_pred,
    })
    df_eval["abs_error"] = np.abs(df_eval["y_real"] - df_eval["y_pred"])

    eps = 1e-8
    df_eval["smape"] = (
        200
        * np.abs(df_eval["y_real"] - df_eval["y_pred"])
        / np.maximum(np.abs(df_eval["y_real"]) + np.abs(df_eval["y_pred"]), eps)
    )

    df_eval["rango_q"] = pd.qcut(
        df_eval["y_real"],
        q=5,
        labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
        duplicates="drop",
    )

    resumen_q = df_eval.groupby("rango_q", observed=False).agg(
        n=("y_real", "size"),
        y_min=("y_real", "min"),
        y_max=("y_real", "max"),
        y_mean=("y_real", "mean"),
        pred_mean=("y_pred", "mean"),
        mae=("abs_error", "mean"),
        mape=("smape", "mean"),
    ).reset_index()

    estadisticos_regresion = pd.DataFrame({
        "Métrica": ["MAE", "R2", "SMAPE medio"],
        "Valor": [
            mean_absolute_error(y_real, y_pred),
            r2_score(y_real, y_pred),
            df_eval["smape"].mean(),
        ],
    })

    print("\n===== Rendimiento regresión =====")
    print(estadisticos_regresion)
    print("\nResumen por cuantiles de y_real:")
    print(resumen_q)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    axes[0].scatter(df_eval["y_real"], df_eval["y_pred"], alpha=0.35)
    min_val = min(df_eval["y_real"].min(), df_eval["y_pred"].min())
    max_val = max(df_eval["y_real"].max(), df_eval["y_pred"].max())
    axes[0].plot([min_val, max_val], [min_val, max_val], linestyle="--")
    axes[0].set_title("Predicción vs valor real")
    axes[0].set_xlabel("y real")
    axes[0].set_ylabel("y pred")
    axes[0].grid(True, alpha=0.3)

    axes[1].bar(resumen_q["rango_q"].astype(str), resumen_q["mae"])
    axes[1].set_title("MAE por cuantiles")
    axes[1].set_xlabel("Cuantil")
    axes[1].set_ylabel("MAE")
    axes[1].grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    plt.show()

    return estadisticos_regresion, resumen_q, df_eval


def evaluar_modelos_disponibles(modelos_disponibles, modo_objetivo, splits, X, y):
    resultados_metricas = {}
    if "clasificacion" in modelos_disponibles:
        resultados_metricas["clasificacion"] = evaluar_clasificacion(
            modelos_disponibles["clasificacion"],
            obtener_splits_para_modo("clasificacion", modo_objetivo, splits, X, y),
        )

    if "regresion" in modelos_disponibles:
        resultados_metricas["regresion"] = evaluar_regresion(
            modelos_disponibles["regresion"],
            obtener_splits_para_modo("regresion", modo_objetivo, splits, X, y),
        )

    return resultados_metricas
