from __future__ import annotations

from chec_local_interpreter.config import (
    DEFAULT_MODEL_DIR,
    DEFAULT_VARIABLES_SELECCION_PATH,
    PROJECT_ROOT,
)


# ---------------------------------------------------------------------------
# Task 1.1 -- new paths/consts resolve under PROJECT_ROOT.
# ---------------------------------------------------------------------------


def test_default_model_dir_resolves_under_project_root():
    assert DEFAULT_MODEL_DIR == PROJECT_ROOT / "data" / "models"
    assert DEFAULT_MODEL_DIR.is_absolute()


def test_default_variables_seleccion_path_resolves_under_project_root():
    assert DEFAULT_VARIABLES_SELECCION_PATH == PROJECT_ROOT / "data" / "Variables_seleccion.xlsx"
    assert DEFAULT_VARIABLES_SELECCION_PATH.is_absolute()


# `SHAP_RANDOM_STATE` se retiro con SHAP: su unico lector era esta prueba, que
# afirmaba que una constante valia lo que decia su propia linea de asignacion.


# `_modelo_mas_reciente` y `DEFAULT_MODEL_BASENAME` se retiraron con el clasificador
# MGCECDL: nombraban `mgcecdl_classifier_best.zip`, un artefacto que ya no existe.
# El simulador y el informe cargan `mil_vano_ventana_v1.pt` por su nombre exacto, sin
# eleccion entre candidatos fechados. Lo mismo con `DEFAULT_OPTUNA_STUDY_PATH`: este
# proyecto no busca hiperparametros, solo lee lo que ya esta en disco.
